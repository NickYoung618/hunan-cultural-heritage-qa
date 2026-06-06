"""
湖湘文化 GraphRAG 问答引擎 v2.0：
融合 Neo4j 图谱检索 + ChromaDB 向量检索 + 百度网络检索 + MIMO LLM 生成。
为 web_ui.py 提供 GraphRAGExpert 接口。
"""
import os
import re
import time
import random
from typing import Any, Generator

import requests
from bs4 import BeautifulSoup
import chromadb
from neo4j import GraphDatabase
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 1. 配置常量
# ============================================================

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_DIR = os.path.join(ROOT_DIR, "chroma_data")
CHROMA_COLLECTION = "huxiang_spirit"

# 已知实体列表（用于关键词匹配图谱查询）
KNOWN_ENTITIES = [
    "王夫之", "周敦颐", "曾国藩", "左宗棠", "魏源",
    "谭嗣同", "黄兴", "蔡锷", "毛泽东",
    "岳麓书院", "湘军", "经世致用",
    "船山先生", "濂溪先生", "涤生",
    "气一元论", "理势合一", "知行合一",
    "太极图说", "通书", "爱莲说", "读通鉴论",
    "程颢", "程颐", "朱熹", "张栻",
    "太平天国", "洋务运动", "戊戌变法",
    "王介之", "王船山", "屈原",
]


# ============================================================
# 2. MIMO API 封装
# ============================================================

def create_mimo_client() -> OpenAI:
    """创建 MIMO API 客户端实例。"""
    return OpenAI(
        api_key=os.getenv("MIMO_API_KEY", "your-mimo-api-key"),
        base_url=os.getenv("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1"),
    )


def call_mimo_llm(prompt: str, model: str = "mimo-v2.5-pro", temperature: float = 0.7) -> str:
    """调用 MIMO LLM，返回完整回答。"""
    client = create_mimo_client()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return response.choices[0].message.content


def stream_mimo_llm(prompt: str, model: str = "mimo-v2.5-pro", temperature: float = 0.7) -> Generator[str, None, None]:
    """调用 MIMO LLM，流式返回 token。"""
    client = create_mimo_client()
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


# ============================================================
# 3. ChromaDB 向量检索接口
# ============================================================

class VectorRetriever:
    """ChromaDB 向量检索器。"""

    def __init__(self, chroma_dir: str = CHROMA_DIR, collection_name: str = CHROMA_COLLECTION):
        self.chroma_dir = chroma_dir
        self.collection_name = collection_name
        self._client = None
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            self._client = chromadb.PersistentClient(path=self.chroma_dir)
            self._collection = self._client.get_collection(name=self.collection_name)
        return self._collection

    def query(self, question: str, n_results: int = 5) -> list[dict]:
        """向量检索，返回最相关的文档块。"""
        try:
            collection = self._get_collection()
            results = collection.query(
                query_texts=[question],
                n_results=n_results,
            )
            documents = []
            if results["documents"] and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i] if results["metadatas"] else {}
                    dist = results["distances"][0][i] if results["distances"] else 0
                    documents.append({
                        "text": doc,
                        "metadata": meta,
                        "distance": dist,
                    })
            return documents
        except Exception as e:
            print(f"⚠️ ChromaDB 查询失败: {e}")
            return []

    def count(self) -> int:
        """返回集合中的文档总数。"""
        try:
            return self._get_collection().count()
        except Exception:
            return 0


# ============================================================
# 4. 百度网络检索接口
# ============================================================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


class WebRetriever:
    """Tavily 网络检索器：AI 优化的搜索引擎 API。"""

    def __init__(self):
        api_key = os.getenv("TAVILY_API_KEY", "")
        self._client = None
        if api_key:
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=api_key)
            except ImportError:
                print("⚠️ tavily-python 未安装，请运行: pip install tavily-python")
        self._local_cache = None

    def _load_local_cache(self) -> dict[str, str]:
        """加载本地已爬取的百科数据作为回退缓存。"""
        if self._local_cache is not None:
            return self._local_cache
        self._local_cache = {}
        for fpath in __import__("glob").glob(os.path.join(ROOT_DIR, "data", "clean_txt", "*.txt")):
            name = os.path.splitext(os.path.basename(fpath))[0]
            try:
                text = open(fpath, "r", encoding="utf-8").read()
                if len(text) > 50:
                    self._local_cache[name] = text
            except Exception:
                pass
        return self._local_cache

    def query(self, question: str, num_results: int = 5) -> list[dict]:
        """网络检索：优先 Tavily API，回退到本地缓存。"""
        # 第一优先：Tavily API
        if self._client:
            try:
                response = self._client.search(
                    query=question,
                    max_results=num_results,
                    search_depth="advanced",
                    include_answer=True,
                )
                results = []
                # Tavily 返回的 answer（如果有）
                answer = response.get("answer", "")
                if answer:
                    results.append({
                        "title": "Tavily 搜索摘要",
                        "snippet": answer[:300],
                        "source": "tavily",
                        "url": "",
                    })
                # Tavily 返回的搜索结果
                for item in response.get("results", []):
                    results.append({
                        "title": item.get("title", ""),
                        "snippet": item.get("content", "")[:300],
                        "source": "tavily",
                        "url": item.get("url", ""),
                    })
                if results:
                    return results[:num_results]
            except Exception as e:
                print(f"⚠️ Tavily 搜索失败: {e}")

        # 回退：本地缓存检索
        return self._search_local_cache(question)

    def _search_local_cache(self, question: str) -> list[dict]:
        """本地缓存检索回退。"""
        cache = self._load_local_cache()
        clean = re.sub(r"[的了吗呢吧啊哦呀？?。.，,、\s]+", " ", question)
        keywords = [kw for kw in re.findall(r"[一-鿿]{2,6}", clean) if len(kw) >= 2]

        results = []
        for name, text in cache.items():
            score = 0
            for kw in keywords:
                if kw in text:
                    score += 1
                if kw in name:
                    score += 2
            if score > 0:
                paragraphs = [p.strip() for p in text.split("\n") if len(p.strip()) > 30]
                best = ""
                best_s = 0
                for para in paragraphs:
                    s = sum(1 for kw in keywords if kw in para)
                    if s > best_s:
                        best_s = s
                        best = para
                if best:
                    results.append({
                        "title": f"本地知识库：{name}",
                        "snippet": best[:300],
                        "source": "local_cache",
                        "score": score,
                    })

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:5]


# ============================================================
# 5. Neo4j 图谱检索接口
# ============================================================

class GraphRetriever:
    """Neo4j 图谱检索器。"""

    def __init__(self):
        uri = os.getenv("NEO4J_URI", "bolt://localhost:8687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "12345678")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def extract_entities(self, question: str) -> list[str]:
        """从问题中提取已知实体名称。"""
        found = []
        for entity in KNOWN_ENTITIES:
            if entity in question:
                found.append(entity)
        return found

    def query_entity_relations(self, entity: str) -> list[dict]:
        """查询某个实体的所有关系。"""
        cypher = """
            MATCH (a)-[r]-(b)
            WHERE a.name CONTAINS $entity
            RETURN a.name AS source, labels(a)[0] AS source_type,
                   type(r) AS relation, r.detail AS detail,
                   b.name AS target, labels(b)[0] AS target_type
        """
        try:
            with self.driver.session() as session:
                result = session.run(cypher, entity=entity)
                return [record.data() for record in result]
        except Exception as e:
            print(f"⚠️ Neo4j 查询失败: {e}")
            return []

    def query_keyword(self, keyword: str) -> list[dict]:
        """模糊搜索实体并返回其关系。"""
        cypher = """
            MATCH (a)-[r]-(b)
            WHERE a.name CONTAINS $keyword OR b.name CONTAINS $keyword
            RETURN a.name AS source, labels(a)[0] AS source_type,
                   type(r) AS relation, r.detail AS detail,
                   b.name AS target, labels(b)[0] AS target_type
        """
        try:
            with self.driver.session() as session:
                result = session.run(cypher, keyword=keyword)
                return [record.data() for record in result]
        except Exception as e:
            print(f"⚠️ Neo4j 查询失败: {e}")
            return []

    def query_relations_for_question(self, question: str) -> list[dict]:
        """智能提取问题中的实体并查询图谱。"""
        entities = self.extract_entities(question)
        if not entities:
            # 尝试用问题中的关键词模糊搜索
            keywords = re.findall(r"[一-鿿]{2,6}", question)
            for kw in keywords:
                if len(kw) >= 2:
                    results = self.query_keyword(kw)
                    if results:
                        return results
            return []

        all_results = []
        for entity in entities[:3]:  # 最多查 3 个实体
            results = self.query_entity_relations(entity)
            all_results.extend(results)
        return all_results


# ============================================================
# 5. GraphRAGExpert 主类（web_ui.py 的接口）
# ============================================================

class GraphRAGExpert:
    """湖湘文化 GraphRAG 专家系统，融合图谱 + 向量 + 网络三路检索。"""

    def __init__(self):
        self.graph = GraphRetriever()
        self.vector = VectorRetriever()
        self.web = WebRetriever()
        self.analytics = _AnalyticsProxy(self.graph)

    def close(self):
        """关闭所有连接。"""
        self.graph.close()

    # 低价值关系类型（家族、重复性连接等），预过滤时降权
    LOW_VALUE_RELATIONS = {
        "父子", "母子", "兄弟", "夫妻", "父女", "曾祖父", "曾祖母",
        "祖父", "祖母", "出生地", "出生于", "病逝于", "居住",
        "并称", "对比评价", "比较研究", "相关事件", "挽联", "挽联评价",
        "鸣冤", "互动", "关系密切", "密切关系", "师徒并称",
    }

    def _prefilter_evidence(self, evidence: list[dict], max_keep: int = 50, is_family_query: bool = False) -> list[dict]:
        """预过滤：去重 + 去低价值关系 + 限制数量。"""
        seen = set()
        high_value = []
        low_value = []

        for item in evidence:
            src = item.get("source", "")
            rel = item.get("relation", "")
            tgt = item.get("target", "")
            key = f"{src}|{rel}|{tgt}"

            if key in seen:
                continue
            seen.add(key)

            if is_family_query:
                # 问家族时，家族关系是高价值
                if rel in self.LOW_VALUE_RELATIONS:
                    high_value.append(item)
                else:
                    low_value.append(item)
            else:
                if rel in self.LOW_VALUE_RELATIONS:
                    low_value.append(item)
                else:
                    high_value.append(item)

        # 高价值优先，总数不超过 max_keep
        result = high_value[:max_keep]
        remaining = max_keep - len(result)
        if remaining > 0:
            result.extend(low_value[:remaining])
        return result

    # 高价值关系类型（直接表明成就/贡献/作品/思想）
    HIGH_VALUE_RELATIONS = {
        "著有", "撰写", "编写", "代表作", "创建", "创办", "建立",
        "领导", "主导", "指挥", "参与", "收复", "平定", "镇压",
        "主张", "核心思想", "思想影响", "受思想影响", "学说",
        "担任", "任职", "任命", "授职",
        "消灭", "进攻", "驻扎", "进驻",
        "上奏", "奏请", "力谏", "建议",
    }

    def _filter_relevant_evidence(self, question: str, evidence: list[dict]) -> list[dict]:
        """智能筛选与问题相关的证据（先预过滤，再按需调用 LLM）。"""
        if not evidence or len(evidence) <= 3:
            return evidence

        # 第一步：判断问题是否和家族/关系相关
        family_keywords = {"家人", "父亲", "母亲", "兄弟", "姐妹", "妻子", "儿子", "女儿", "亲属", "家族", "后代"}
        q_keywords_raw = set(re.findall(r"[一-鿿]{2,4}", re.sub(r"[的了吗呢吧啊哦呀]|\s+", " ", question)))
        is_family_query = bool(q_keywords_raw & family_keywords)

        # 第二步：去重 + 预过滤
        evidence = self._prefilter_evidence(evidence, max_keep=50, is_family_query=is_family_query)

        if len(evidence) <= 8:
            return evidence

        # 第三步：从问题中提取关键词
        clean_q = re.sub(r"[的了吗呢吧啊哦呀]|\s+", " ", question)
        q_keywords = set(re.findall(r"[一-鿿]{2,4}", clean_q))
        for i in range(len(question) - 1):
            sub = question[i:i+2]
            if re.match(r"[一-鿿]{2}$", sub):
                q_keywords.add(sub)

        # 第四步：按关键词快速评分
        scored = []
        for item in evidence:
            rel = item.get("relation", "")
            tgt = item.get("target", "")
            score = 0

            if is_family_query:
                # 问家族相关：家族关系高分，其他低分
                if rel in self.LOW_VALUE_RELATIONS:
                    score += 3
                else:
                    score -= 1
            else:
                # 问非家族相关
                # 核心：关系类型是否包含问题中的核心意图词
                # 先提取问题中的核心意图词（排除实体名）
                entity_chars = set()
                for kw in q_keywords:
                    if len(kw) >= 3:  # 长词可能是实体名
                        entity_chars.update(kw)
                intent_chars = set()
                for kw in q_keywords:
                    for c in kw:
                        if c not in entity_chars or len(kw) <= 2:
                            intent_chars.add(c)

                rel_chars = set(rel)
                # 关系类型包含意图字符（最高优先级）
                if intent_chars & rel_chars:
                    score += 5
                # 高价值关系加分
                if rel in self.HIGH_VALUE_RELATIONS:
                    score += 3
                # 低价值关系减分
                if rel in self.LOW_VALUE_RELATIONS:
                    score -= 2

            scored.append((score, item))

        # 按分数降序排列
        scored.sort(key=lambda x: x[0], reverse=True)

        # 如果高分段（score >= 3）已经有足够结果，直接返回
        high_score = [item for score, item in scored if score >= 3]
        if len(high_score) >= 5:
            return high_score[:20]

        # 否则返回所有非负分的
        result = [item for score, item in scored if score >= 0]
        return result[:20] if result else evidence[:20]

    def ask_stream(self, user_question: str) -> Generator[dict, None, None]:
        """流式问答：先检索证据，再流式生成回答。

        Yields:
            dict: 事件类型包括 cypher, evidence, token, done
        """
        t_start = time.time()

        # --- 第一步：图谱检索 ---
        entities = self.graph.extract_entities(user_question)
        raw_evidence = self.graph.query_relations_for_question(user_question)

        # LLM 智能过滤：从全部关系中筛选与问题相关的
        graph_evidence = self._filter_relevant_evidence(user_question, raw_evidence)

        if graph_evidence:
            # 生成真实的 Cypher 查询展示
            entity_filter = " OR ".join([f'a.name CONTAINS "{e}"' for e in entities[:3]])
            if not entity_filter:
                entity_filter = 'a.name CONTAINS "..."'
            cypher_info = (
                f"MATCH (a)-[r]-(b)\n"
                f"WHERE {entity_filter}\n"
                f"RETURN a.name, type(r), b.name\n"
                f"（已由 LLM 从 {len(raw_evidence)} 条中筛选出 {len(graph_evidence)} 条相关证据）"
            )
            yield {"type": "cypher", "data": cypher_info}
            yield {"type": "evidence", "data": graph_evidence}

        # --- 第二步：向量检索 ---
        vector_docs = self.vector.query(user_question, n_results=5)

        # --- 第三步：网络检索（百度搜索） ---
        web_results = self.web.query(user_question, num_results=5)
        if web_results:
            web_lines = []
            for r in web_results:
                web_lines.append(f"- {r['title']}：{r['snippet']}")
            yield {"type": "web", "data": web_results}

        # --- 第四步：构建证据上下文 ---
        evidence_parts = []

        if graph_evidence:
            graph_lines = []
            for item in graph_evidence:
                src = item.get("source", "")
                rel = item.get("relation", "")
                tgt = item.get("target", "")
                detail = item.get("detail", "")
                line = f"- {src} --[{rel}]--> {tgt}"
                if detail:
                    line += f"：{detail}"
                graph_lines.append(line)
            evidence_parts.append("[图谱证据]\n" + "\n".join(graph_lines))

        if vector_docs:
            vector_lines = []
            for doc in vector_docs:
                meta = doc.get("metadata", {})
                source = meta.get("entity_name", "")
                text = doc["text"]
                vector_lines.append(f"- [{source}] {text}")
            evidence_parts.append("[向量检索证据]\n" + "\n".join(vector_lines))

        if web_results:
            web_lines = []
            for r in web_results:
                web_lines.append(f"- {r['title']}：{r['snippet']}")
            evidence_parts.append("[网络检索证据 - 百度搜索]\n" + "\n".join(web_lines))

        evidence_text = "\n\n".join(evidence_parts) if evidence_parts else "未找到相关证据。"

        # --- 第四步：LLM 流式生成 ---
        system_prompt = """你是一位专业的湖湘文化学者，精通湖南历史人物、思想流派和文化遗产。
请基于以下检索到的证据，回答用户的问题。

【回答要求】：
1. 严格基于提供的证据回答，不要编造信息
2. 如果有原文引用，必须用双引号标出
3. 回答要专业、连贯，像一位历史学家在讲解
4. 如果证据不足，明确告知用户"当前知识库中相关资料有限"
5. 回答使用中文"""

        full_prompt = f"""{system_prompt}

用户问题：{user_question}

{evidence_text}

请给出你的回答："""

        for token in stream_mimo_llm(full_prompt):
            yield {"type": "token", "data": token}

        elapsed = round(time.time() - t_start, 2)
        yield {"type": "done", "data": "完成", "elapsed_seconds": elapsed}

    def ask(self, user_question: str) -> str:
        """非流式问答，返回完整回答。"""
        answer = ""
        for event in self.ask_stream(user_question):
            if event["type"] == "token":
                answer += event["data"]
        return answer

    def query_shortest_path(self, name1: str, name2: str) -> str:
        """查询两个实体之间的最短路径，返回格式化文本。"""
        path_data = self.analytics.shortest_path(name1, name2)
        if not path_data:
            return f"未找到「{name1}」与「{name2}」之间的关系路径。"

        lines = [f"## {name1} → {name2} 关系路径\n"]
        for i, segment in enumerate(path_data, 1):
            src = segment.get("from", segment.get("source", ""))
            rel = segment.get("relation", "")
            tgt = segment.get("to", segment.get("target", ""))
            detail = segment.get("detail", "")
            line = f"{i}. **{src}** —[{rel}]→ **{tgt}**"
            if detail:
                line += f"\n   > {detail}"
            lines.append(line)

        return "\n".join(lines)


# ============================================================
# 6. 分析代理（桥接 GraphAnalytics）
# ============================================================

class _AnalyticsProxy:
    """代理类，桥接 GraphAnalytics 模块。"""

    def __init__(self, graph_retriever: GraphRetriever):
        self._driver = graph_retriever.driver

    def shortest_path(self, start_name: str, end_name: str, max_depth: int = 6) -> list[dict]:
        """查询最短路径。"""
        cypher = """
            MATCH p = shortestPath((a)-[*..$max_depth]-(b))
            WHERE a.name = $start_name AND b.name = $end_name
            RETURN
                [node IN nodes(p) | {name: node.name, type: labels(node)[0]}] AS nodes,
                [rel IN relationships(p) | {
                    from: startNode(rel).name,
                    to: endNode(rel).name,
                    relation: type(rel),
                    detail: COALESCE(rel.detail, '')
                }] AS relations
        """
        try:
            with self._driver.session() as session:
                result = session.run(cypher, start_name=start_name, end_name=end_name, max_depth=max_depth)
                records = list(result)

            if not records:
                # 模糊匹配回退
                cypher_fuzzy = """
                    MATCH p = shortestPath((a)-[*..$max_depth]-(b))
                    WHERE a.name CONTAINS $start_name AND b.name CONTAINS $end_name
                    RETURN
                        [node IN nodes(p) | {name: node.name, type: labels(node)[0]}] AS nodes,
                        [rel IN relationships(p) | {
                            from: startNode(rel).name,
                            to: endNode(rel).name,
                            relation: type(rel),
                            detail: COALESCE(rel.detail, '')
                        }] AS relations
                    LIMIT 1
                """
                with self._driver.session() as session:
                    result = session.run(cypher_fuzzy, start_name=start_name, end_name=end_name, max_depth=max_depth)
                    records = list(result)

            if not records:
                return []

            record = records[0]
            path_segments = []
            relations = record["relations"]
            nodes = record["nodes"]

            for i, rel in enumerate(relations):
                path_segments.append({
                    "from": rel["from"],
                    "to": rel["to"],
                    "relation": rel["relation"],
                    "detail": rel.get("detail", ""),
                })

            return path_segments

        except Exception as e:
            print(f"⚠️ 最短路径查询失败: {e}")
            return []

    def full_report(self) -> dict:
        """生成图谱分析报告。"""
        report = {}

        # 度中心性 Top 10
        try:
            cypher_degree = """
                MATCH (n)
                OPTIONAL MATCH (n)-[r]-()
                WITH n, count(r) AS degree
                ORDER BY degree DESC LIMIT 10
                RETURN n.name AS name, labels(n)[0] AS type, degree
            """
            with self._driver.session() as session:
                result = session.run(cypher_degree)
                report["degree_top10"] = [record.data() for record in result]
        except Exception:
            report["degree_top10"] = []

        # PageRank 近似（加权入出度）
        try:
            cypher_pr = """
                MATCH (n)
                OPTIONAL MATCH (n)<-[r_in]-()
                OPTIONAL MATCH (n)-[r_out]->()
                WITH n, count(r_in) AS in_deg, count(r_out) AS out_deg
                WITH n, (in_deg * 1.0 + out_deg * 0.5) AS pagerank_approx
                ORDER BY pagerank_approx DESC LIMIT 10
                RETURN n.name AS name, labels(n)[0] AS type, pagerank_approx
            """
            with self._driver.session() as session:
                result = session.run(cypher_pr)
                report["pagerank_top10"] = [record.data() for record in result]
        except Exception:
            report["pagerank_top10"] = []

        # 介数中心性近似
        try:
            cypher_between = """
                MATCH (n)
                OPTIONAL MATCH (a)-[*2]-(n)-[*2]-(b)
                WHERE a <> b
                WITH n, count(DISTINCT a) + count(DISTINCT b) AS betweenness_approx
                ORDER BY betweenness_approx DESC LIMIT 10
                RETURN n.name AS name, labels(n)[0] AS type, betweenness_approx
            """
            with self._driver.session() as session:
                result = session.run(cypher_between)
                report["betweenness_top10"] = [record.data() for record in result]
        except Exception:
            report["betweenness_top10"] = []

        report["gds_available"] = False
        return report


# ============================================================
# 7. 兼容旧接口
# ============================================================

def init_chromadb():
    """初始化 ChromaDB（兼容旧版调用）。"""
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    return collection


# ============================================================
# 8. 主测试入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 湖湘文化 GraphRAG 问答引擎 v2.0 测试")
    print("=" * 60)

    expert = GraphRAGExpert()

    # 测试向量检索
    print(f"\n📊 ChromaDB 文档数: {expert.vector.count()}")

    # 测试问答
    test_questions = [
        "王夫之的核心思想是什么？",
        "曾国藩和左宗棠是什么关系？",
        "岳麓书院的历史？",
    ]

    for i, q in enumerate(test_questions, 1):
        print(f"\n{'='*60}")
        print(f"[测试 {i}] {q}")
        print("-" * 60)
        for event in expert.ask_stream(q):
            if event["type"] == "token":
                print(event["data"], end="", flush=True)
            elif event["type"] == "evidence":
                print(f"\n📎 证据数: {len(event['data'])}")
            elif event["type"] == "done":
                print(f"\n⏱️ 耗时: {event.get('elapsed_seconds', '?')} 秒")

    expert.close()
    print(f"\n{'='*60}")
    print("✅ 测试完成！")
