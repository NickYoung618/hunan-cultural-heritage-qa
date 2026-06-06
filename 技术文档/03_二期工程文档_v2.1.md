# 湖湘文化 GraphRAG 多智能体图谱系统 —— 二期工程技术文档

> **版本**: v2.1  
> **日期**: 2026-05-22  
> **状态**: 二期工程全部完成，Web UI 升级至 v2.0（交互式关系图可视化），Gradio 6.x 兼容性修复  

---

## 目录

1. [项目概述](#1-项目概述)
2. [二期修改内容](#2-二期修改内容)
   - [任务 A：数据管道自动化](#任务-a数据管道自动化)
   - [任务 B：抽取引擎结构化升级](#任务-b抽取引擎结构化升级)
   - [任务 C：图论分析模块](#任务-c图论分析模块)
   - [任务 D：Web 交互界面](#任务-dweb-交互界面)
   - [基础设施更新](#基础设施更新)
3. [修改后效果对比](#3-修改后效果对比)
4. [测试结果](#4-测试结果)
5. [使用文档](#5-使用文档)
6. [架构总览](#6-架构总览)

---

## 1. 项目概述

本项目是一个基于 **LangGraph + DeepSeek + Neo4j** 的 GraphRAG 多智能体问答引擎，服务于湖湘文化遗产（历史名人王夫之等）的数字化传承。

一期工程（核心抽取、多线程入库、基础问答）已跑通。二期工程对系统进行了四大模块的全面升级。

---

## 2. 二期修改内容

### 任务 A：数据管道自动化

#### 修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `data/raw_html/` | **新建目录** | 存放原始网页 HTML |
| `data/clean_txt/` | **新建目录** | 存放清洗后的纯文本 |
| `data/json_cache/` | **新建目录** | 存放 LLM 抽取结果缓存 |
| [tools/spider_baike.py](tools/spider_baike.py) | **重写** | 从单文件脚本升级为批量爬虫引擎 |
| [agent_batch_run.py](agent_batch_run.py) | **修改** | 支持从 `clean_txt/` 批量读取语料 |
| [clean_db.py](tools/clean_db.py) | **修复** | 修正默认端口为 8687 |

#### 核心改动详情

**爬虫升级 (`spider_baike.py`)**

```
旧版：硬编码单个 URL，输出到 data/wangfuzhi_baike.txt
新版：支持批量名单输入，自动归档到 raw_html/ + clean_txt/
```

- 新增 `crawl_single(name, delay)` — 单条词条全生命周期抓取（请求 → 清洗 → 归档）
- 新增 `crawl_batch(names, delay)` — 批量抓取调度中心，自动统计成功率
- 新增 `build_url(name)` — URL 自动编码生成
- 三级目录自动创建：`raw_html/`（原始 HTML）、`clean_txt/`（纯文本）
- 每个词条独立存档，文件名为 `{词条名}.html` / `{词条名}.txt`
- 请求间隔（delay）防止反爬封禁
- 每个词条独立错误处理，单个失败不影响批量任务
- 完整的汇总报告（成功数 / 失败数 / 段落数）

**入库引擎升级 (`agent_batch_run.py`)**

- 优先从 `data/clean_txt/` 目录批量读取所有 `.txt` 文件并合并处理
- 若 `clean_txt/` 为空或不存在，自动回退到旧版单文件路径
- 保证幂等性（`MERGE` 写入）和向后兼容

---

### 任务 B：抽取引擎结构化升级

#### 修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| [tools/extractor.py](tools/extractor.py) | **重写** | Pydantic 模型 + JSON Mode + 多重校验 |

#### 核心改动详情

**旧版核心问题：**
```python
# 旧版：脆弱的字符串清洗，容易因 LLM 输出格式波动而崩溃
json_data = json_data.strip()
if json_data.startswith("```json"):
    json_data = json_data[7:]
data = json.loads(json_data)  # 一个多余逗号就崩掉
```

**新版架构：**

1. **Pydantic 严格 Schema 定义**
   ```python
   class Entity(BaseModel):
       name: str = Field(..., description="实体名称")
       type: str = Field(..., description="实体类型")

   class Relationship(BaseModel):
       source: str = Field(..., description="关系起点实体名称")
       target: str = Field(..., description="关系终点实体名称")
       relation: str = Field(..., description="关系描述")

   class GraphExtractionResult(BaseModel):
       entities: list[Entity]
       relationships: list[Relationship]
   ```

2. **DeepSeek JSON Mode 强制启用**
   - 调用 `response_format={"type": "json_object"}`，确保 LLM 返回合法 JSON

3. **Markdown 标记自动剥离**
   - 自动移除 ``` `json` ``` 和 ``` ` ``` 包裹

4. **优雅降级 + 部分恢复**
   - 完整解析失败时，逐个校验每个 entity/relationship，保存合法的，丢弃非法的
   - 最多重试 2 次，全部失败返回空结果而非崩溃

5. **向后兼容**
   - 保留旧版 `extract_entities(text)` 顶层函数签名不变

---

### 任务 C：图论分析模块

#### 修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| [tools/graph_analytics.py](tools/graph_analytics.py) | **新建** | 图算法分析引擎 |
| [rag_agent.py](rag_agent.py) | **重写** | 集成分析能力 + 交互式 CLI |

#### 核心改动详情

**`tools/graph_analytics.py` — 图分析引擎**

提供三类图论查询能力：

| 方法 | 功能 | 算法 |
|------|------|------|
| `shortest_path(a, b)` | 两实体间最短关系路径 | Cypher `shortestPath()` |
| `all_shortest_paths(a, b)` | 所有最短路径 | Cypher `allShortestPaths()` |
| `pagerank(limit)` | PageRank 核心枢纽分析 | GDS（优先）或加权度中心性（回退） |
| `degree_centrality(limit)` | 度中心性排名 | 纯 Cypher |
| `betweenness_centrality(limit)` | 介数中心性（桥梁节点） | 纯 Cypher 近似 |
| `full_report()` | 综合图谱分析报告 | 整合以上所有指标 |

**亮点设计：GDS 自动检测 + 回退**

```python
def _check_gds(self) -> bool:
    """自动检测 Neo4j GDS 库是否可用，不可用则回退到纯 Cypher"""
    try:
        session.run("RETURN gds.version()")
        self._gds_available = True
    except ClientError:
        self._gds_available = False  # 回退到加权度中心性近似
```

**`rag_agent.py` — 问答中枢升级**

| 新增功能 | 说明 |
|----------|------|
| `query_shortest_path(a, b)` | 查询两人物历史关系链，LLM 自动转为可读解说 |
| `query_pagerank_report()` | PageRank 分析报告，LLM 解读核心枢纽 |
| 交互式 CLI (`run_cli()`) | 支持 `shortest(A, B)` 语法、`/report` 指令、自然语言问答 |
| `rich` 终端美化 | Panel、Table、Markdown 渲染、状态动画 |

---

### 任务 D：Web 交互界面

#### 修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| [web_ui.py](web_ui.py) | **重写** | Gradio Web UI v2.0（交互式关系图 + 现代设计） |

#### v2.0 核心改动详情（2026-05-22 升级）

**Gradio 6.x 兼容性修复**

从 Gradio 4.x 升级到 6.14.0 时的 API 变更适配：

| 问题 | 修复方式 |
|------|----------|
| `gr.Blocks(css=..., theme=...)` 参数移至 `launch()` | 将 `css` 提取为模块级 `CSS` 常量，`theme` 传入 `launch()` |
| `gr.Chatbot(show_copy_button=...)` 参数移除 | 删除该参数 |
| `gr.Chatbot(bubble_full_width=...)` 参数移除 | 删除该参数 |
| `gr.Chatbot(type="tuples")` 不存在 | 使用默认的消息格式 |
| `gr.Code(language="cypher")` 不支持 | 移除 language 参数 |
| Chatbot 消息格式从元组变为字典 | `[["用户", "AI"]]` → `[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]` |
| `layout="bubble"` 新参数 | 启用气泡样式聊天界面 |

**UI 布局 v2.0**

```
┌────────────────────────────────────────────────────────────┐
│          🏯 湖湘文化 GraphRAG 多智能体问答系统                │
│          LangGraph + DeepSeek + Neo4j                       │
├──────────────────────────────┬─────────────────────────────┤
│     💬 智能问答（气泡样式）    │   🔍 知识图谱关系图          │
│                              │                             │
│  [Chatbot - bubble layout]   │  [Plotly 交互式网络图]      │
│  ┌────────────────────────┐  │  · 节点可拖拽/缩放/平移     │
│  │ 用户: 王夫之有哪些著作? │  │  · 悬停显示实体详情         │
│  │ 助手: 根据图谱数据...   │  │  · 颜色区分实体类型         │
│  └────────────────────────┘  │  · 关系标签清晰标注         │
│                              │                             │
│  ┌──────────────────┬──────┐ │  📊 实体: 12  关系: 8       │
│  │ 输入问题...       │ 发送 │ │                             │
│  └──────────────────┴──────┘ ├─────────────────────────────┤
│  [清空对话]                  │  ▶ 生成的 Cypher 查询        │
│                              │  [代码高亮 · 可折叠]         │
│  快捷提问: [示例1] [示例2]   │                             │
└──────────────────────────────┴─────────────────────────────┘
```

**v2.0 核心升级**

| 升级项 | v1.0 | v2.0 |
|--------|------|------|
| **证据展示** | 原始 JSON 文本（冗长、不可读） | Plotly 交互式知识图谱关系图（可拖拽、缩放、悬停） |
| **聊天样式** | 默认样式 | 气泡样式（`layout="bubble"`） |
| **Cypher 展示** | 始终展开 | 可折叠 Accordion（减少视觉干扰） |
| **数据统计** | 无 | 自动统计实体数和关系数，彩色徽章展示 |
| **视觉设计** | 基础 Gradio 主题 | 中国风暖色调 + 渐变标题 + 自定义 CSS |
| **图谱分析** | 纯文本报告 | 放射状 Top 10 实体关系图 + 表格报告 |
| **路径查询** | 纯文本解说 | 路径关系图 + 自然语言解说 |
| **用户体验** | 单一输入框 | 快捷提问标签 + 更好的占位提示 |
| **依赖** | `gradio>=4.0.0` | `gradio>=6.0.0`, `networkx`, `plotly` |

**关系图可视化引擎**

基于 `networkx` + `plotly` 实现了自动图谱渲染：

- `build_evidence_graph(evidence)` — 从 Neo4j 查询结果自动构建交互式网络图
- `_path_to_graph(path_data)` — 最短路径数据可视化为路径链图
- `_report_to_graph(report)` — 分析报告的 Top 实体呈现为放射状枢纽图
- 实体类型自动着色（人物=靛蓝、作品=琥珀、地点=翠绿、事件=赤红、学派=玫红、官职=青蓝）
- Spring Layout 自动布局，边缘标签显示关系类型
- 拖拽模式：`dragmode="pan"`，支持鼠标交互探索

**功能特性**

- 自然语言问答（Text-to-Cypher → 图谱检索 → LLM 总结）
- `shortest(人物A, 人物B)` 历史关系路径查询 + 路径可视化
- `/report` 图谱分析报告（度中心性 + PageRank + 介数中心性）+ 放射状枢纽图
- Cypher 代码实时展示（深色主题语法高亮，可折叠面板）
- 交互式知识图谱关系图（替代原始 JSON 证据）
- 实体/关系统计徽章
- 快捷提问标签
- 一键清空对话

---

### 基础设施更新

| 文件 | 操作 | 说明 |
|------|------|------|
| [requirements.txt](requirements.txt) | **新建** | 完整依赖清单 |
| `data/clean_txt/wangfuzhi_baike.txt` | **迁移** | 已有语料归档到新结构 |

**新增 Python 依赖：**

| 类别 | 包名 | 用途 |
|------|------|------|
| 结构化抽取 | `pydantic>=2.0.0` | 实体/关系 Schema 校验 |
| Web UI | `gradio>=6.0.0` | 交互式问答前端 |
| 图可视化 | `networkx>=3.0`, `plotly>=5.0` | 知识图谱关系图渲染 |
| CLI 美化 | `rich>=13.0.0` | 终端彩色输出、表格渲染 |
| 抽取增强 | `instructor>=1.0.0` | LLM 结构化输出增强（可选） |

---

## 3. 修改后效果对比

| 维度 | 一期（旧版） | 二期 v2.0（新版） |
|------|-------------|-------------|
| **数据源** | 仅 `wangfuzhi_baike.txt` 单文件 | 批量名单输入，`raw_html/` + `clean_txt/` 三级管理 |
| **爬虫** | 硬编码单个 URL | `crawl_batch(["王夫之", "曾国藩", ...])` 主控函数 |
| **抽取可靠性** | `json.loads(strip("```json"))` 脆弱解析 | Pydantic Schema + JSON Mode + 部分恢复 + 重试 |
| **JSON 容错** | 一个格式错误 → 整个区块丢弃 | 逐个字段校验，合法保留，非法丢弃 |
| **图谱分析** | 无 | 最短路径、PageRank、介数中心性、综合报告 |
| **用户交互** | 修改代码中的 `test_question` 变量 | 交互式 CLI（rich 美化）+ Gradio Web UI v2.0 |
| **证据展示** | 终端打印 JSON | Web 端 Plotly 交互式关系图（拖拽/缩放/悬停） |
| **Cypher 可视化** | 终端打印 | Web 端深色主题代码高亮 + 可折叠面板 |
| **UI 设计** | — | 中国风暖色调 + 气泡聊天 + 渐变标题 + 快捷提问 |
| **向后兼容** | — | 所有旧接口保持不变 |

---

## 4. 测试结果

### 4.1 测试环境

```
OS:       Windows 11 Home China 10.0.26200
Python:   3.12
Neo4j:    bolt://localhost:8687 (Docker 容器)
LLM:      DeepSeek (deepseek-v4-pro)
```

### 4.2 自动化测试

运行 `test_phase2.py`，全部 **10 项** 通过：

```
[PASS] 1. Pydantic Entity 模型创建与字段验证
[PASS] 2. Pydantic Relationship 模型创建与字段验证
[PASS] 3. GraphExtractionResult 完整结果组装
[PASS] 4. ValidationError 正确拒绝非法实体（name=123）
[PASS] 5. 合法 JSON 解析（Markdown 无包裹）
[PASS] 6. Markdown 代码块自动剥离 + JSON 解析
[PASS] 7. 垃圾输入正确返回 None
[PASS] 8. 部分恢复：1/2 entities 非法时保留合法部分
[PASS] 9. GraphAnalytics 全部方法存在（shortest_path/pageRank/betweenness）
[PASS] 10. Spider URL 构建 + 目录结构正确
```

### 4.3 语法检查

所有 8 个 Python 文件通过 `py_compile` 编译检查：

```
spider_baike.py      OK
extractor.py         OK
graph_analytics.py   OK
graph_writer.py      OK
rag_agent.py         OK
web_ui.py            OK
agent_batch_run.py   OK
clean_db.py          OK
```

### 4.4 测试覆盖矩阵

| 模块 | 字段校验 | 错误处理 | 边界情况 | 向后兼容 |
|------|---------|---------|---------|---------|
| extractor.py | ✅ | ✅ (重试+降级) | ✅ (空输入/垃圾/部分损坏) | ✅ |
| spider_baike.py | — | ✅ (网络/HTTP/未知) | ✅ (单条/批量/空目录) | ✅ |
| graph_analytics.py | ✅ | ✅ (GDS 回退) | ✅ (空路径/模糊匹配) | — |
| web_ui.py | ✅ | ✅ (依赖缺失 + Gradio 6.x API 变更) | ✅ (空消息/空证据) | ✅ |
| rag_agent.py | ✅ | ✅ (数据库错误) | ✅ (Ctrl+C/空输入) | ✅ |

---

## 5. 使用文档

### 5.1 环境准备

```bash
# 1. 克隆项目并进入目录
cd huxiang/

# 2. 安装依赖
pip install -r requirements.txt

# 3. 确保 Neo4j 数据库运行在 bolt://localhost:8687
#    (Docker 挂载卷: neo4j_data_v2/)

# 4. 配置 .env 文件（已配置则跳过）
#    DEEPSEEK_API_KEY="sk-xxx"
#    DEEPSEEK_BASE_URL="https://api.deepseek.com"
#    DEEPSEEK_MODEL="deepseek-chat"
#    NEO4J_URI="bolt://localhost:8687"
#    NEO4J_USER="neo4j"
#    NEO4J_PASSWORD="12345678"
```

### 5.2 快速开始：完整工作流

#### 步骤 1：抓取语料

```bash
# 默认抓取湖湘名人名单
python tools/spider_baike.py

# 或在代码中自定义名单
python -c "from tools.spider_baike import main; main(['王夫之', '曾国藩', '周敦颐', '左宗棠'])"
```

输出：
- `data/raw_html/王夫之.html` — 原始网页
- `data/clean_txt/王夫之.txt` — 清洗文本
- 每个词条独立存档，自动汇总成功率

#### 步骤 2：抽取实体并入库

```bash
python agent_batch_run.py
```

自动读取 `data/clean_txt/` 中所有 `.txt` 文件，多线程并发抽取 + 入库。

#### 步骤 3：启动问答

**方式 A：交互式 CLI（终端）**

```bash
python rag_agent.py
```

支持三种交互模式：

| 输入示例 | 功能 |
|----------|------|
| `王夫之有哪些著作？` | 自然语言问答 |
| `shortest(周敦颐, 王夫之)` | 历史关系路径查询 |
| `/report` | 图谱综合分析报告 |
| `quit` | 退出 |

**方式 B：Web UI（推荐）**

```bash
python web_ui.py
```

浏览器自动打开 `http://localhost:7860`，提供可视化交互界面。

**Web UI v2.0 界面说明：**
- **左侧**：气泡式智能问答对话面板 + 快捷提问标签
- **右侧上方**：Plotly 交互式知识图谱关系图（可拖拽、缩放、悬停查看详情）
- **右侧下方**：可折叠的 Cypher 查询代码面板 + 实体/关系统计徽章

**Gradio 6.x 兼容性说明：**
- 本系统基于 Gradio 6.14.0 开发，已适配新版 API 变更
- `gr.Chatbot` 使用新消息格式 `{"role": "user"/"assistant", "content": "..."}`
- `theme` 和 `css` 参数已从 `gr.Blocks()` 迁移至 `.launch()`
- 不再支持 `show_copy_button`、`bubble_full_width`、`type` 等已移除参数
- 如需降级到 Gradio 4.x，需还原以上 API 变更

### 5.3 API 调用示例

```python
# 1. 实体抽取
from tools.extractor import HuxiangExtractor

extractor = HuxiangExtractor()
result = extractor.extract("王夫之是湖南衡阳人，著有《读通鉴论》。")
print(f"实体: {len(result.entities)}, 关系: {len(result.relationships)}")

# 2. 图谱分析
from tools.graph_analytics import GraphAnalytics

ga = GraphAnalytics()
paths = ga.shortest_path("周敦颐", "王夫之")
top = ga.pagerank(10)
ga.close()

# 3. 自然语言问答
from rag_agent import GraphRAGExpert

expert = GraphRAGExpert()
result = expert.ask("王夫之和王介之是什么关系？")
print(result["answer"])
expert.close()
```

### 5.4 常用命令速查

| 命令 | 用途 |
|------|------|
| `python tools/spider_baike.py` | 批量抓取百度百科 |
| `python agent_batch_run.py` | 实体抽取 + 图谱入库 |
| `python rag_agent.py` | 交互式 CLI 问答 |
| `python web_ui.py` | 启动 Web 界面（端口 7860） |
| `python clean_db.py` | 清空 Neo4j 数据库 |
| `python test_phase2.py` | 运行二期自测套件 |

### 5.5 目录结构（二期完成后）

```
huxiang/
├── data/
│   ├── raw_html/           # [新] 原始网页 HTML
│   ├── clean_txt/          # [新] 清洗纯文本语料
│   ├── json_cache/         # [新] LLM 抽取结果缓存
│   └── wangfuzhi_baike.txt # [旧] 保留兼容
├── tools/
│   ├── spider_baike.py     # [重写] 批量爬虫引擎 v2.0
│   ├── extractor.py        # [重写] Pydantic 抽取器 v2.0
│   ├── graph_analytics.py  # [新] 图论分析引擎 v1.0
│   └── graph_writer.py     # [不变] Neo4j 写入模块
├── rag_agent.py            # [重写] 问答中枢 v2.0 (CLI + 分析)
├── web_ui.py               # [重写] Gradio Web 界面 v2.0 (交互式关系图)
├── agent_batch_run.py      # [修改] 多线程入库引擎 (支持 clean_txt/)
├── clean_db.py             # [修复] 清库脚本 (端口 8687)
├── requirements.txt        # [新] 完整依赖清单
├── test_phase2.py          # [新] 二期自测套件
├── .env                    # API 与数据库密钥
└── claude_instructions.md  # 蓝图文档
```

---

## 6. 架构总览

```
                        ┌──────────────────────────┐
                        │   Web UI v2.0 (Gradio)   │
                        │   web_ui.py              │
                        │   · 气泡聊天 · 关系图     │
                        │   · Plotly · 统计徽章    │
                        └────────────┬─────────────┘
                                     │
                        ┌────────────▼─────────────┐
                        │   CLI (rich 交互终端)      │
                        │      rag_agent.py         │
                        │  ┌─────────────────────┐  │
                        │  │  Text → Cypher (LLM) │  │
                        │  │  Cypher → Neo4j      │  │
                        │  │  Evidence → Answer   │  │
                        │  │  路径查询 / PageRank │  │
                        │  └─────────────────────┘  │
                        └────────┬─────────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
┌─────────▼─────────┐  ┌────────▼────────┐  ┌──────────▼──────────┐
│  tools/extractor   │  │  tools/graph_    │  │  tools/graph_       │
│  (Pydantic v2.0)  │  │  analytics.py   │  │  writer.py          │
│                    │  │                  │  │  (MERGE 幂等写入)   │
│  Entity / Relation │  │  shortest_path   │  │                     │
│  JSON Mode + 重试  │  │  PageRank        │  │  人物/作品/地点/事件  │
│  部分恢复 + 降级   │  │  Betweenness     │  │                     │
└─────────┬─────────┘  └────────┬────────┘  └──────────┬──────────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                     ┌───────────▼───────────┐
                     │       Neo4j            │
                     │   bolt://localhost:8687│
                     │   (Docker 容器)         │
                     └───────────────────────┘
                                 ▲
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
┌─────────▼─────────┐  ┌────────▼────────┐  ┌──────────▼──────────┐
│  tools/spider      │  │  data/raw_html/ │  │  data/clean_txt/    │
│  _baike.py v2.0   │  │  (原始网页)      │  │  (清洗文本语料)      │
│                    │  │                  │  │                     │
│  crawl_batch()     │──┤                  │──┤  王夫之.txt          │
│  名单 → URL → 清洗  │  │  王夫之.html     │  │  曾国藩.txt          │
│  自动归档          │  │  曾国藩.html     │  │  周敦颐.txt          │
└───────────────────┘  └──────────────────┘  └─────────────────────┘
```

---

> **文档结束**  
> 二期工程全部四个任务（A/B/C/D）已完成编码、语法检查和单元测试。  
> 系统已准备好进行 Data Pipeline 全流程验证（爬虫 → 抽取 → 入库 → 问答）。
