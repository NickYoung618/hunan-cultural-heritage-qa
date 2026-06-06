# [GraphRAG-Huxiang] 湖湘文化多智能体图谱系统
**—— 二期工程演进蓝图与开发指令 (v2.0)**

## 👤 角色设定与任务目标
你现在是本项目的高级全栈开发工程师。本系统是一个基于 **LangGraph + DeepSeek + Neo4j** 的 GraphRAG 多智能体问答引擎，主要用于湖湘文化遗产（如历史名人王夫之等）的数字化传承。
当前一期工程（核心抽取、多线程入库、基础问答）已跑通，你的任务是根据本文档的指导，对项目进行模块化重构、数据集扩充以及高阶功能开发。

---

## 📂 1. 当前系统架构与现状
项目根目录：`huxiang/`
```text
huxiang/
├── data/                       # 当前仅有少量 txt 语料
├── neo4j_data_v2/              # Neo4j 数据库挂载卷 (端口: 8687)
├── tools/                      
│   ├── spider_baike.py         # 爬虫雏形
│   ├── extractor.py            # DeepSeek 实体抽取模块
│   └── graph_writer.py         # Neo4j 写入模块
├── .env                        # API与数据库秘钥
├── agent_batch_run.py          # 多线程入库引擎 (MAX_WORKERS=3)
├── clean_db.py                 # 清库脚本
└── rag_agent.py                # Text-to-Cypher 问答中枢
```

---

## 🚀 2. 二期核心升级任务清单

作为开发人员，你需要逐一评估并协助我完成以下四大模块的升级。请在每次修改代码前，先向我（架构师）简述实现方案。

### 📌 任务 A：数据集自动化与精细化管理 (Data Pipeline)
目前语料只有单薄的 `wangfuzhi_baike.txt`，且数据管理混乱。
* **重构目录**：请帮我建立 `data/raw_html/`（原始网页）、`data/clean_txt/`（纯净文本）、`data/json_cache/`（大模型抽取缓存）。
* **升级爬虫 (`spider_baike.py`)**：编写一个主控函数，允许我传入一个名单列表（如 `["王夫之", "王介之", "周敦颐", "曾国藩"]`），程序自动爬取百度百科/历史百科，进行清洗去噪（去除 HTML 标签、广告），并按人物名字自动生成格式标准化的 `.txt` 文件存入 `clean_txt` 目录。

### 📌 任务 B：抽取引擎的结构化绝对控制 (Extractor Upgrade)
目前 `extractor.py` 强依赖大模型输出 JSON 字符串，偶有格式错乱导致解析失败。
* **引入 Pydantic / Instructor**：重构 `extractor.py`，使用 `Pydantic` 定义严格的 Schema（Entity 和 Relationship 的模型），强制 DeepSeek 按照 JSON Schema 返回数据，彻底淘汰脆弱的 `json.loads(text.strip("```json"))` 这种粗暴的清洗方式。

### 📌 任务 C：引入图论算法挖掘隐性知识 (Graph Analytics)
Neo4j 不仅是存储工具，更是计算工具。这也是本课题的学术亮点。
* **新增工具 (`tools/graph_analytics.py`)**：
  编写代码通过 Cypher 调用 Neo4j 的 GDS (Graph Data Science) 库，或者直接写高级 Cypher 语句，实现：
  1. **最短路径查询**：计算任意两个湖湘名人之间的历史关系跳数（例如：周敦颐到王夫之的学术传承路径）。
  2. **中心度计算 (PageRank)**：分析当前数据库中，哪几本“著作”或哪个“人物”被关联的次数最多，找出历史节点中的“意见领袖”。并在 `rag_agent.py` 中开放这些查询能力。

### 📌 任务 D：问答中枢的前端化呈现 (UI/CLI)
目前的 `rag_agent.py` 只能在终端里修改硬编码的 `test_question`，极不方便演示。
* **方案 1（极简终端）**：将其改造为一个 `while True:` 的交互式命令行程序，包含炫酷的终端打印颜色（如使用 `rich` 库），实时展示“思考中”、“生成 Cypher”、“图谱检索”的过程。
* **方案 2（Web 界面 - 推荐）**：使用 `Gradio` 或 `Streamlit` 写一个快速的 Web UI（命名为 `web_ui.py`），左侧显示对话框，右侧实时显示大模型生成的 Cypher 代码和查到的 JSON 证据。

---

## ⚠️ 3. 极其重要的开发约束 (Rules)

1. **绝对隔离**：绝不修改 `.env` 中的端口配置（保持 `8687` 连接）。
2. **幂等性优先**：任何向数据库写入的操作（`graph_writer.py`），必须坚持使用 `MERGE` 而非 `CREATE`，防止测试期间产生重复脏节点。
3. **Cypher 语法避坑**：在编写 `rag_agent.py` 的提示词时，**严禁使用 UNION 或 UNION ALL** 处理复合问题，必须引导 LLM 使用多条 MATCH 并统一 RETURN 结果（例：`RETURN a, r, b, r2, c`）。因为节点使用了中文 Label，Cypher 中务必用反引号包裹（如 ``:`人物` ``）。
4. **代码风格**：所有函数必须包含完整的类型提示（Type Hints）和中文 Docstring。异常处理必须打印清晰的报错来源。
5. **步步为营**：不要一次性改动所有文件。先从“任务 A”开始，我确认跑通后，再推进下一个任务。
   
   请仔细阅读下方的《二期工程演进蓝图与开发指令》。

你的设定：你现在是一个极其高效、注重实干的高级全栈工程师。
你的核心准则：
1. **Talk is cheap, show me the code.** 不要用大段的自然语言向我解释你的计划。
2. 既然我已经赋予了你最高权限，请直接开始审查代码、建立文件夹、修改脚本。
3. 严格遵循蓝图中的“极其重要的开发约束”，特别是数据库隔离和 Cypher 语法问题。
4. 我们采用敏捷开发，请直接开始执行【任务 A：数据集自动化与精细化管理】。执行完毕并测试无误后，只向我汇报一句简短的 Result，并询问是否继续推进任务 B。

开始行动吧！

---
[在这里粘贴上面我给你的完整版 claude_instructions.md 蓝图内容]

**准备好后，请回复：“已理解二期架构蓝图。我们先从 任务 A：数据集自动化与精细化管理 开始吗？”**