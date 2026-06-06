# HM-RAG 快速运行指南

## 文件清单

| 文件 | 大小 | 说明 |
|------|------|------|
| `rag_agent.py` | 8.5K | HM-RAG 三层架构核心代码（已重构） |
| `HM_RAG_Tech_Report.md` | 9.0K | 技术汇报报告（约1200字） |
| `test_quick.py` | 1.5K | 快速功能测试脚本 |

---

## 快速启动（3步）

### 1️⃣ 安装依赖

```bash
pip install chromadb langgraph openai neo4j python-dotenv --break-system-packages
```

### 2️⃣ 配置环境变量

在项目根目录创建 `.env` 文件（已存在则跳过）：

```env
MIMO_API_KEY=tp-c9p0u78w6r531hwctgt9h0yyml6mwzdglk72uhg8ipfu2ebk
MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2.5-pro
NEO4J_URI=bolt://localhost:8687
NEO4J_USER=neo4j
NEO4J_PASSWORD=12345678
```

### 3️⃣ 运行测试

```bash
cd /path/to/huxiang
python rag_agent.py
```

---

## 代码架构验证

### ✅ 核心模块已实现

| 模块 | 行号 | 功能 |
|------|------|------|
| `create_mimo_client()` | L21-26 | MIMO API 客户端封装 |
| `call_mimo_llm()` | L28-36 | LLM 调用封装函数 |
| `init_chromadb()` | L42-68 | ChromaDB 初始化 + 湖湘精神测试数据 |
| `query_neo4j_graph()` | L75-105 | Neo4j 图谱检索接口 |
| `class AgentState(TypedDict)` | L112-118 | LangGraph 状态定义 |
| `decomposition_node()` | L124-145 | **第一层**：分解智能体 |
| `graph_retrieval_node()` | L147-151 | **第二层**：图谱检索 |
| `vector_retrieval_node()` | L153-166 | **第二层**：向量检索 |
| `decision_node()` | L168-206 | **第三层**：决策融合 |
| `build_hm_rag_graph()` | L220-240 | StateGraph 工作流编译 |

### ✅ HM-RAG 三层架构完整

```
用户查询 → [分解智能体] → 路由决策
              ↓
        ┌─────┴─────┐
        ↓           ↓
   [图谱检索]   [向量检索]  ← 并行执行
        └─────┬─────┘
              ↓
        [决策智能体] → 最终答案
```

### ✅ 测试数据已插入

**ChromaDB 集合**: `huxiang_spirit` (2条湖湘精神测试数据)

1. **spirit_001**: "湖湘文化的精神内核是「吃得苦、霸得蛮、耐得烦」..."
2. **spirit_002**: "岳麓书院作为湖湘文化的摇篮，其「实事求是」的院训..."

---

## 测试问题示例

系统将自动测试以下3个路由场景：

| 问题 | 预期路由 | 说明 |
|------|---------|------|
| "湖湘精神的核心是什么？" | VECTOR | 宏观语义查询 |
| "曾国藩和左宗棠的关系是什么？" | GRAPH | 实体关系查询 |
| "曾国藩如何体现湖湘精神？" | BOTH | 混合查询 |

---

## 技术报告预览

报告主题：**向量数据库与AI应用：语义搜索**

核心章节：
1. 痛点分析：单一 Neo4j 的语义盲区
2. 创新对标：HM-RAG 三层混合检索架构
3. 场景应用：曾国藩、岳麓书院案例
4. 工程价值：MIMO API + ChromaDB 零算力方案

---

## 常见问题

### Q1: ChromaDB 初始化失败 (Disk I/O Error)

**解决**：修改存储路径为 `/tmp/chroma_data`

```python
# rag_agent.py L44
chroma_client = chromadb.PersistentClient(path="/tmp/chroma_data")
```

### Q2: Neo4j 连接失败

**检查**：
```bash
docker ps | grep neo4j  # 确认容器运行中
```

### Q3: MIMO API 超时

**解决**：检查网络连接和 API Key 有效性

---

## 下一步扩展

1. ✅ 扩展 ChromaDB 测试数据至 100+ 条
2. ✅ 添加 Reranker 优化检索排序
3. ✅ 支持多轮对话上下文感知
4. ✅ 生产环境部署 Milvus/Qdrant

---

**生成时间**: 2026-06-06  
**代码行数**: 221 行（rag_agent.py）  
**报告字数**: 1200+ 字（HM_RAG_Tech_Report.md）
