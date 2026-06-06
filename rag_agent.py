"""
HM-RAG 问答系统 v1.0：基于 ACM MM 2025 论文的三层混合检索架构。
实现：分解智能体 -> 多源并行检索 -> 决策融合 的完整 LangGraph 工作流。
技术栈：MIMO API (mimo-v2.5-pro) + Neo4j + ChromaDB + LangGraph
"""
import os
import re
from typing import Any, TypedDict, Literal
from openai import OpenAI
from neo4j import GraphDatabase
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
import chromadb

load_dotenv()

# ============================================================
# 1. MIMO API 封装（DeepSeek mimo-v2.5-pro）
# ============================================================

def create_mimo_client() -> OpenAI:
    """创建 MIMO API 客户端实例。"""
    return OpenAI(
        api_key=os.getenv("MIMO_API_KEY", "your-mimo-api-key"),
        base_url=os.getenv("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
    )

def call_mimo_llm(prompt: str, model: str = "mimo-v2.5-pro", temperature: float = 0.7) -> str:
    """调用 MIMO LLM 的封装函数。"""
    client = create_mimo_client()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature
    )
    return response.choices[0].message.content

# ============================================================
# 2. ChromaDB 本地初始化 + 湖湘精神测试数据
# ============================================================

def init_chromadb() -> chromadb.Collection:
    """初始化本地 ChromaDB 并插入湖湘精神测试数据。"""
    chroma_client = chromadb.PersistentClient(path="/tmp/chroma_data")
    collection = chroma_client.get_or_create_collection(
        name="huxiang_spirit",
        metadata={"hnsw:space": "cosine"}
    )

    test_documents = [
        {
            "id": "spirit_001",
            "document": "湖湘文化的精神内核是「吃得苦、霸得蛮、耐得烦」。这种精神源自屈原的「路漫漫其修远兮，吾将上下而求索」的坚韧不拔，以及曾国藩「打脱牙和血吞」的刚毅血性。在岳麓书院的千年传承中，这一精神不断被强化和传承，形成了独特的地域文化基因。",
            "metadata": {"source": "湖湘精神研究", "era": "千年传承", "theme": "血性与坚韧"}
        },
        {
            "id": "spirit_002",
            "document": "岳麓书院作为湖湘文化的摇篮，其「实事求是」的院训深刻影响了中国近现代史。从王夫之的「经世致用」到毛泽东的「实践论」，湖湘学派始终强调知行合一。这种精神在曾国藩的湘军治理中体现为「扎硬寨、打死仗」的务实作风，在左宗棠的「抬棺出征」中则表现为誓死捍卫国家主权的担当精神。",
            "metadata": {"source": "岳麓书院研究", "era": "近现代", "theme": "经世致用"}
        }
    ]

    collection.upsert(
        ids=[doc["id"] for doc in test_documents],
        documents=[doc["document"] for doc in test_documents],
        metadatas=[doc["metadata"] for doc in test_documents]
    )

    return collection

# ============================================================
# 3. Neo4j 图谱接口（调用现有 GraphAnalytics）
# ============================================================

def query_neo4j_graph(question: str) -> list[dict[str, Any]]:
    """调用现有的图谱分析模块进行检索。"""
    from tools.graph_analytics import GraphAnalytics

    ga = GraphAnalytics()

    entities = []
    for keyword in ["曾国藩", "王夫之", "左宗棠", "岳麓书院", "屈原", "毛泽东"]:
        if keyword in question:
            entities.append(keyword)

    if not entities:
        ga.close()
        return []

    entity = entities[0]
    cypher = f"""
        MATCH (a)-[r]-(b)
        WHERE a.name CONTAINS "{entity}"
        RETURN a.name AS source, type(r) AS relation, b.name AS target, r.detail AS detail
        LIMIT 20
    """

    try:
        with ga.driver.session() as session:
            result = session.run(cypher)
            return [record.data() for record in result]
    except Exception as e:
        print(f"Neo4j query error: {e}")
        return []
    finally:
        ga.close()

# ============================================================
# 4. LangGraph AgentState 定义
# ============================================================

class AgentState(TypedDict):
    """HM-RAG 智能体状态定义。"""
    question: str
    route_decision: Literal["GRAPH", "VECTOR", "BOTH"]
    graph_evidence: list[dict]
    vector_evidence: list[str]
    final_answer: str

# ============================================================
# 5. HM-RAG 三层节点函数
# ============================================================

def decomposition_node(state: AgentState) -> AgentState:
    """第一层：分解智能体。分析查询意图，路由到最优检索分支。"""
    question = state["question"]

    classification_prompt = f"""你是一个查询意图分类器。分析以下问题属于哪种类型：

问题：{question}

分类规则：
- GRAPH：询问具体的实体关系、人物关系、历史事件连线（如"曾国藩和左宗棠的关系"）
- VECTOR：询问宏观文化精神、抽象概念、整体评价（如"湖湘精神的核心是什么"）
- BOTH：问题同时涉及具体实体和宏观概念（如"曾国藩如何体现湖湘精神"）

只输出一个词：GRAPH 或 VECTOR 或 BOTH
"""

    decision = call_mimo_llm(classification_prompt, temperature=0.1).strip()

    if decision not in ["GRAPH", "VECTOR", "BOTH"]:
        decision = "BOTH"

    return {**state, "route_decision": decision}

def graph_retrieval_node(state: AgentState) -> AgentState:
    """第二层：Neo4j 图谱检索节点。"""
    question = state["question"]
    graph_data = query_neo4j_graph(question)
    return {**state, "graph_evidence": graph_data}

def vector_retrieval_node(state: AgentState) -> AgentState:
    """第二层：ChromaDB 向量检索节点。"""
    question = state["question"]

    chroma_client = chromadb.PersistentClient(path="/tmp/chroma_data")
    collection = chroma_client.get_collection(name="huxiang_spirit")

    results = collection.query(
        query_texts=[question],
        n_results=2
    )

    documents = results["documents"][0] if results["documents"] else []
    return {**state, "vector_evidence": documents}

def decision_node(state: AgentState) -> AgentState:
    """第三层：决策智能体。融合多源证据，生成最终答案。"""
    question = state["question"]
    route = state["route_decision"]
    graph_evidence = state.get("graph_evidence", [])
    vector_evidence = state.get("vector_evidence", [])

    evidence_sections = []

    if route in ["GRAPH", "BOTH"] and graph_evidence:
        graph_text = "\n".join([
            f"- {item.get('source', '')} --[{item.get('relation', '')}]--> {item.get('target', '')}: {item.get('detail', 'No detail')}"
            for item in graph_evidence
        ])
        evidence_sections.append(f"[Graph Evidence]\n{graph_text}")

    if route in ["VECTOR", "BOTH"] and vector_evidence:
        vector_text = "\n".join([f"- {doc}" for doc in vector_evidence])
        evidence_sections.append(f"[Vector Evidence]\n{vector_text}")

    evidence_combined = "\n\n".join(evidence_sections) if evidence_sections else "No relevant evidence found."

    answer_prompt = f"""你是一位专业的湖湘文化学者。请基于以下检索到的证据，回答用户的问题。

用户问题：{question}

{evidence_combined}

【回答要求】：
1. 严格基于提供的证据回答，不要编造信息
2. 如果有原文引用，必须用双引号标出
3. 回答要专业、连贯，像一位历史学家在讲解
4. 如果证据不足，明确告知用户

请给出你的回答：
"""

    final_answer = call_mimo_llm(answer_prompt, temperature=0.7)
    return {**state, "final_answer": final_answer}

# ============================================================
# 6. LangGraph 条件路由函数
# ============================================================

def route_decision(state: AgentState) -> str:
    """根据分解智能体的决策，路由到对应的检索分支。"""
    return state["route_decision"]

# ============================================================
# 7. 构建 LangGraph StateGraph
# ============================================================

def build_hm_rag_graph() -> StateGraph:
    """构建 HM-RAG 三层混合检索工作流图。"""
    workflow = StateGraph(AgentState)

    workflow.add_node("decomposition", decomposition_node)
    workflow.add_node("graph_retrieval", graph_retrieval_node)
    workflow.add_node("vector_retrieval", vector_retrieval_node)
    workflow.add_node("decision", decision_node)

    workflow.set_entry_point("decomposition")

    workflow.add_conditional_edges(
        "decomposition",
        route_decision,
        {
            "GRAPH": "graph_retrieval",
            "VECTOR": "vector_retrieval",
            "BOTH": "graph_retrieval"
        }
    )

    workflow.add_conditional_edges(
        "graph_retrieval",
        lambda state: "decision" if state["route_decision"] == "GRAPH" else "vector_retrieval",
        {
            "decision": "decision",
            "vector_retrieval": "vector_retrieval"
        }
    )

    workflow.add_edge("vector_retrieval", "decision")
    workflow.add_edge("decision", END)

    return workflow.compile()

# ============================================================
# 8. 主测试入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("[START] HM-RAG 三层混合检索系统 v1.0 测试启动")
    print("=" * 60)

    print("\n[INIT] 正在创建 ChromaDB 集合和插入湖湘精神测试数据...")
    collection = init_chromadb()
    print(f"[OK] ChromaDB 集合 '{collection.name}' 已创建，包含 {collection.count()} 条记录")

    print("\n[BUILD] 正在构建 HM-RAG 工作流图...")
    hm_rag = build_hm_rag_graph()
    print("[OK] LangGraph StateGraph 已编译完成")

    test_questions = [
        "湖湘精神的核心是什么？",
        "曾国藩和左宗棠的关系是什么？",
        "曾国藩如何体现湖湘精神？",
    ]

    for i, question in enumerate(test_questions, 1):
        print(f"\n{'='*60}")
        print(f"[TEST {i}] {question}")
        print("-" * 60)

        initial_state = {
            "question": question,
            "route_decision": "",
            "graph_evidence": [],
            "vector_evidence": [],
            "final_answer": ""
        }

        result = hm_rag.invoke(initial_state)

        print(f"[ROUTE] {result['route_decision']}")
        print(f"[GRAPH] Evidence count: {len(result['graph_evidence'])}")
        print(f"[VECTOR] Evidence count: {len(result['vector_evidence'])}")
        print(f"\n[ANSWER]\n{result['final_answer']}")

    print(f"\n{'='*60}")
    print("[DONE] 测试完成！")
    print("=" * 60)
