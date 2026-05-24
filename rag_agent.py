"""
GraphRAG 问答中枢 v3.0：流式输出 + 大小模型路由 + 语义缓存。
支持 Text-to-Cypher 自然语言查询、图谱分析、交互式 CLI（rich 终端美化）和 Web UI 后端。
"""
import os
import re
import time
from typing import Any, Generator
from openai import OpenAI
from neo4j import GraphDatabase
from dotenv import load_dotenv
from tools.graph_analytics import GraphAnalytics
from cache_tool.semantic_cache import get_cache

load_dotenv()


class GraphRAGExpert:
    """湖湘文化 GraphRAG 问答专家（v3.0 流式 + 双模型 + 缓存增强版）"""

    def __init__(self) -> None:
        # Neo4j 连接
        self.neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:8687")
        self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_pwd = os.getenv("NEO4J_PASSWORD", "12345678")
        self.driver = GraphDatabase.driver(
            self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_pwd)
        )

        # DeepSeek LLM 连接
        self.llm_client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL"),
        )

        # 大小模型路由
        self.fast_model = os.getenv("DEEPSEEK_FAST_MODEL", "deepseek-v4-flash")
        self.pro_model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

        # 图谱分析引擎
        self.analytics = GraphAnalytics()

        # 语义缓存
        self.cache = get_cache()

    def close(self) -> None:
        """释放所有连接。"""
        self.driver.close()
        self.analytics.close()

    def _execute_cypher(self, query: str) -> list[dict[str, Any]]:
        """执行 Cypher 语句并返回结果。"""
        try:
            with self.driver.session() as session:
                result = session.run(query)
                return [record.data() for record in result]
        except Exception as e:
            return [{"error": f"数据库执行出错: {e}"}]

    def _serialize_evidence(self, evidence: list[dict]) -> list[dict]:
        """将 Neo4j 原始对象转为 LLM 易读的干净字典，清晰展示 detail 等属性。"""
        clean = []
        for record in evidence:
            item = {}
            for key, val in record.items():
                if hasattr(val, "_properties"):
                    info = {}
                    # 节点属性
                    if hasattr(val, "labels"):
                        labels = list(val.labels) if val.labels else []
                        info["_label"] = labels[0] if labels else ""
                    # 关系属性
                    if hasattr(val, "type"):
                        info["_type"] = val.type
                    # 写入所有自定义属性（包括 detail）
                    for pk, pv in val._properties.items():
                        info[pk] = pv
                    item[key] = info
                elif isinstance(val, dict):
                    item[key] = val
                else:
                    item[key] = str(val)
            clean.append(item)
        return clean

    # ------------------------------------------------------------------
    # 传统同步接口（CLI 用，保持向后兼容）
    # ------------------------------------------------------------------

    def ask(self, user_question: str, verbose: bool = True) -> dict[str, Any]:
        """Text-to-Cypher 问答（同步版，CLI 用）。"""
        if verbose:
            print(f"\n👤 你问: {user_question}")
            print("-" * 50)

        # 语义缓存检查
        cached = self.cache.lookup(user_question)
        if cached:
            if verbose:
                print("⚡ [缓存命中] 直接返回历史回答")
            return cached

        if verbose:
            print("🤖 [思考中] 正在将问题翻译为图谱查询语言 (Cypher)...")

        # Step 1: NL → Cypher（快模型）
        cypher_query = self._generate_cypher(user_question)
        if verbose:
            print(f"🔍 [生成的 Cypher]\n{cypher_query}\n")

        # Step 2: 执行 Cypher
        if verbose:
            print("🕸️  [检索中] 正在图数据库中检索证据...")
        db_results = self._execute_cypher(cypher_query)
        if verbose:
            print(f"📦 [检索到的图谱数据] {db_results}\n")

        # Step 3: LLM 生成回答（大模型）
        if not db_results or ("error" in str(db_results[0]) if db_results else False):
            answer = "抱歉，我在湖湘文化图谱中没有检索到与该问题相关的确切连线数据。"
        else:
            if verbose:
                print("✍️  [总结中] 正在根据图谱证据撰写最终答案...\n")
            answer = self._generate_answer(user_question, db_results)

        if verbose:
            print("✨ [最终回答] ✨")
            print(answer)

        result = {
            "cypher": cypher_query,
            "evidence": db_results,
            "answer": answer,
        }

        # 存入缓存
        if db_results and not ("error" in str(db_results[0]) if db_results else False):
            self.cache.store(user_question, answer, cypher_query, db_results)

        return result

    # ------------------------------------------------------------------
    # 流式接口（Web UI 用，将事件逐个 yield 给前端）
    # ------------------------------------------------------------------

    def ask_stream(
        self, user_question: str
    ) -> Generator[dict[str, Any], None, None]:
        """Text-to-Cypher 问答（流式版，支持大小模型路由和语义缓存）。

        逐事件 yield dict：
          {"type": "thinking", "message": str}    — 状态提示
          {"type": "cypher", "data": str}         — Cypher 生成完毕
          {"type": "evidence", "data": list}      — 图谱检索完毕
          {"type": "token", "data": str}           — 回答流式 token
          {"type": "done", "answer": str, "cypher": str, "evidence": list}
        """
        t_start = time.time()

        # ---- 缓存检查 ----
        cached = self.cache.lookup(user_question)
        if cached:
            yield {"type": "thinking", "message": "缓存命中，直接返回历史回答"}
            yield {"type": "cypher", "data": cached["cypher"]}
            yield {"type": "evidence", "data": cached["evidence"]}
            yield {"type": "token", "data": cached["answer"]}
            yield {
                "type": "done",
                "answer": cached["answer"],
                "cypher": cached["cypher"],
                "evidence": cached["evidence"],
                "elapsed_seconds": round(time.time() - t_start, 2),
            }
            return

        # ---- Step 1: NL → Cypher（快模型） ----
        yield {"type": "thinking", "message": "正在将问题翻译为图谱查询语言..."}
        cypher_query = self._generate_cypher(user_question)
        yield {"type": "cypher", "data": cypher_query}

        # ---- Step 2: 执行 Cypher ----
        yield {"type": "thinking", "message": "正在图数据库中检索证据..."}
        db_results = self._execute_cypher(cypher_query)
        yield {"type": "evidence", "data": db_results}

        # ---- Step 3: 流式生成回答（大模型） ----
        if not db_results or ("error" in str(db_results[0]) if db_results else False):
            fallback = "抱歉，我在湖湘文化图谱中没有检索到与该问题相关的确切连线数据。"
            yield {"type": "token", "data": fallback}
            yield {
                "type": "done",
                "answer": fallback,
                "cypher": cypher_query,
                "evidence": db_results,
                "elapsed_seconds": round(time.time() - t_start, 2),
            }
            return

        yield {"type": "thinking", "message": "正在撰写回答..."}

        full_answer = ""
        for token in self._generate_answer_stream(user_question, db_results):
            full_answer += token
            yield {"type": "token", "data": token}

        yield {
            "type": "done",
            "answer": full_answer,
            "cypher": cypher_query,
            "evidence": db_results,
            "elapsed_seconds": round(time.time() - t_start, 2),
        }

        # 存入缓存
        if db_results and not ("error" in str(db_results[0]) if db_results else False):
            self.cache.store(user_question, full_answer, cypher_query, db_results)

    # ------------------------------------------------------------------
    # LLM 调用 — 快模型生成 Cypher
    # ------------------------------------------------------------------

    def _generate_cypher(self, question: str) -> str:
        """调用**快模型**将自然语言问题翻译为 Cypher 查询语句。"""
        cypher_prompt = f"""
你是一个熟练的 Neo4j Cypher 专家。你的任务是将用户的中文问题转换为可以在 Neo4j 中执行的 Cypher 查询语句。

已知我的湖湘文化图谱中包含的节点标签有：人物、作品、地点、事件、概念、时间、学派、官职。
关系主要包含人物之间的关系（如兄弟、师傅）、人物与作品的关系（如撰写）、人物与地点的关系（如隐居）等。

【极其重要 — 图谱属性说明】：
1. 图谱中的关系（Edge）上挂载了一个名为 detail 的属性，里面存储了重要的历史原文、评价原话等关键信息。
2. 图谱中的节点（Node）上挂载了一个名为 description 的属性，里面存储了该实体的详细背景、思想解释、生平概括等原文描述。

【强制 RETURN 格式】：
由于 Python Neo4j 驱动在序列化对象时会丢失属性，RETURN 子句必须使用以下固定格式，同时提取关系的 detail 和节点的 description（双重证据）：

    RETURN a.name AS a_name, labels(a)[0] AS a_type,
           a.description AS a_description,
           type(r) AS relation,
           r.detail AS detail,
           b.name AS b_name, labels(b)[0] AS b_type,
           b.description AS b_description

    严禁使用 RETURN a, r, b 这种会丢失 detail 和 description 属性的写法！

【绝对强制法则 — 违反任何一条都会导致查询彻底失败，必须严格遵守】：

🛑 法则零：禁止硬编码关系类型 (No Hardcoded RelTypes)
   - 当用户询问两人关系或家族网络时，绝对禁止在 Cypher 中指定具体的 relationship type。
   - 例如绝对不能写 -[r:儿子]->、-[r:妻子]->、-[r:师傅]-> 等任何硬编码的关系类型！
   - 必须使用无向且无类型的泛匹配 -[r]-，把与核心节点相连的所有一度或二度节点全部 RETURN 回来。
   - 正确示例：MATCH (a:`人物`)-[r*1..2]-(b:`人物`) WHERE a.name CONTAINS "王夫之"
   - 原因：图谱缺乏标准化本体，关系名称由 LLM 盲目猜测，命中率必然为 0。让下游回答大模型根据返回的 type(r) 和 r.detail 做逻辑推理！

🛑 法则一：禁止使用弃用的 id() 函数 (Neo4j 5.x 语法)
   - 当前使用的是 Neo4j 5.x 版本，id() 函数已被彻底弃用，使用会报 01N02 警告。
   - 如果需要判断两个节点是否不同，直接比较节点本身，例如 WHERE a <> b。
   - 绝对不允许出现 id(a) <> id(b) 或任何包含 id() 的写法！

🛑 法则二：独立实体直接查询法则 (Direct Entity Match for Concepts)
   - 当用户询问某个具体的【概念】、【思想】、【作品】或【特定事件】（例如"气一元论是什么"、"《读通鉴论》写了什么"）时，不要强制要求它与主语（如王夫之）有关系连线！
   - 你应该直接 MATCH 那个概念本身的节点，并返回它的 description。
   - ✅ 正确示例：MATCH (n) WHERE n.name CONTAINS "气一元论" RETURN n.name, labels(n)[0] AS label, n.description
   - ❌ 错误示例：MATCH (a)-[r]-(b) WHERE a.name CONTAINS "王夫之" AND b.name CONTAINS "气一元论"（如果节点孤立，此查询将失败返回空）。

【高级检索法则 — 必须严格遵守】：

1. ⭐ 全面启用模糊匹配：
   - 严禁在 MATCH 节点时对 name 使用绝对等于（=），必须全部改为 CONTAINS。
   - 正确示例：WHERE a.name CONTAINS "王夫之"
   - 错误示例：WHERE a.name = "王夫之" 或 MATCH (a:`人物` {{name: "王夫之"}})
   - 原因：中文人名、地名可能存在别名或部分匹配需求，CONTAINS 可避免因字面差异导致的漏检。

2. ⭐ 增强多跳推理与代词解析：
   - 当用户提问包含间接代词或亲属称谓（如"第四个儿子""他的老师""好友""父亲"）时，严禁将代词作为节点名查询！
   - 此时应生成 1 到 2 度的宽泛路径查询，让 LLM 依靠返回的全量上下文自行判断。
   - 正确示例：MATCH (a:`人物`)-[r*1..2]-(b:`人物`) WHERE a.name CONTAINS "王夫之"
   - 如果问题明确提到了两个具体实体（如"曾国藩对王夫之的评价"），用 WHERE 条件匹配两个实体，查询它们之间的路径。
   - 如果问题只提到一个实体，以该实体为中心查询其所有关系。

3. ⭐ 强制返回双重证据：
   - RETURN 语句中必须同时返回连线上的 r.detail 和节点上的 a.description、b.description（若存在）。
   - 这样即使某些节点是"孤立节点"（无连线），其 description 中的原文解释也能被检索到，不会丢失信息。

【其他规则】：
- 因为节点标签是中文的，所以在 Cypher 中必须使用反引号包裹，例如：MATCH (n:`人物`)
- 只输出 Cypher 代码，不要任何解释。
- 代码必须用 ```cypher 和 ``` 包裹。
- 严禁使用 UNION 或 UNION ALL。
- 每次查询最多返回 50 条结果。

用户问题：{question}
"""
        response = self.llm_client.chat.completions.create(
            model=self.fast_model,  # 快模型：低延迟
            messages=[{"role": "user", "content": cypher_prompt}],
            temperature=0.1,
        )
        cypher_reply = response.choices[0].message.content

        match = re.search(r"```cypher\n(.*?)\n```", cypher_reply, re.DOTALL)
        return match.group(1).strip() if match else cypher_reply.strip()

    # ------------------------------------------------------------------
    # LLM 调用 — 大模型生成回答（同步版，CLI 用）
    # ------------------------------------------------------------------

    def _generate_answer(self, question: str, evidence: list[dict]) -> str:
        """调用**大模型**基于图谱证据生成自然语言回答。"""
        clean_evidence = self._serialize_evidence(evidence)
        final_prompt = f"""
你是一位专业的湖湘文化学者。请严格基于以下从图数据库中检索到的 JSON 关系数据，回答用户的问题。

用户问题：{question}

检索到的图谱数据：
{clean_evidence}

【极其严格的引用规则 — 必须遵守】：
1. 仔细检查每条数据中的 detail 字段（关系上的原文摘抄）和 description 字段（节点上的背景/思想解释）。两者都是证据来源，不可遗漏。
2. 如果数据中包含 detail 或 description 字段且有原文内容，你必须用双引号（""）直接引用原文，严禁只做宽泛的概括或用自己的话转述。
3. 严禁使用你的预训练知识进行脑补或编造。你的回答必须 100% 来源于上述图谱数据。
4. 如果图谱数据中有节点和关系但对不上用户问题的细节，必须明确告知用户"根据当前的图谱记录，暂无该问题的详细记载"。
5. 如果某条数据没有 detail 和 description 字段，可以简要描述该关系的类型，但不要编造细节。
6. 回答要连贯、专业，像一位历史学家在讲解，引用原文时自然嵌入回答中。
"""
        response = self.llm_client.chat.completions.create(
            model=self.pro_model,  # 大模型：高质量推理
            messages=[{"role": "user", "content": final_prompt}],
            temperature=0.7,
        )
        return response.choices[0].message.content

    # ------------------------------------------------------------------
    # LLM 调用 — 大模型流式生成回答（Web UI 用）
    # ------------------------------------------------------------------

    def _generate_answer_stream(
        self, question: str, evidence: list[dict]
    ) -> Generator[str, None, None]:
        """调用**大模型**流式生成回答，逐 token yield 给前端。"""
        clean_evidence = self._serialize_evidence(evidence)
        final_prompt = f"""
你是一位专业的湖湘文化学者。请严格基于以下从图数据库中检索到的 JSON 关系数据，回答用户的问题。

用户问题：{question}

检索到的图谱数据：
{clean_evidence}

【极其严格的引用规则 — 必须遵守】：
1. 仔细检查每条数据中的 detail 字段（关系上的原文摘抄）和 description 字段（节点上的背景/思想解释）。两者都是证据来源，不可遗漏。
2. 如果数据中包含 detail 或 description 字段且有原文内容，你必须用双引号（""）直接引用原文，严禁只做宽泛的概括或用自己的话转述。
3. 严禁使用你的预训练知识进行脑补或编造。你的回答必须 100% 来源于上述图谱数据。
4. 如果图谱数据中有节点和关系但对不上用户问题的细节，必须明确告知用户"根据当前的图谱记录，暂无该问题的详细记载"。
5. 如果某条数据没有 detail 和 description 字段，可以简要描述该关系的类型，但不要编造细节。
6. 回答要连贯、专业，像一位历史学家在讲解，引用原文时自然嵌入回答中。
"""
        response = self.llm_client.chat.completions.create(
            model=self.pro_model,
            messages=[{"role": "user", "content": final_prompt}],
            temperature=0.7,
            stream=True,
        )
        for chunk in response:
            content = chunk.choices[0].delta.content
            if content:
                yield content

    # ------------------------------------------------------------------
    # 图谱分析查询
    # ------------------------------------------------------------------

    def query_shortest_path(self, start_name: str, end_name: str) -> str:
        """查询两个历史人物之间的最短关系路径（自然语言回答）。"""
        paths = self.analytics.shortest_path(start_name, end_name)

        if not paths:
            return f"在当前的湖湘文化图谱中，未找到「{start_name}」与「{end_name}」之间的关联路径。"

        prompt = f"""
你是一位湖湘文化学者。请将以下图谱路径数据转化为一段通俗易懂的历史关系解说。

查询：{start_name} 到 {end_name} 的关系路径
路径数据：{paths}

请用「学术传承链」或「历史关系链」的口吻，一步步解读这条路径，让读者看懂这两个人物之间是如何关联起来的。
"""
        response = self.llm_client.chat.completions.create(
            model=self.pro_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return response.choices[0].message.content

    def query_pagerank_report(self) -> str:
        """获取图谱 PageRank 分析的自然语言报告。"""
        top_entities = self.analytics.pagerank(10)

        if not top_entities:
            return "当前图谱中暂无足够的实体数据用于 PageRank 分析。"

        prompt = f"""
你是一位数据分析师。请根据以下湖湘文化知识图谱的 PageRank 排名数据，撰写一段简短的分析报告（150字以内）。

PageRank Top 10：
{top_entities}

请指出哪一个实体是图谱中的「核心枢纽」，以及这个排名揭示了怎样的知识结构特征。
"""
        response = self.llm_client.chat.completions.create(
            model=self.pro_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return response.choices[0].message.content


# --- 交互式 CLI（方案 1：rich 终端美化） ---

def run_cli() -> None:
    """启动交互式命令行问答循环（使用 rich 美化输出）。"""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.markdown import Markdown
        from rich.table import Table

        console = Console()
        use_rich = True
    except ImportError:
        use_rich = False
        print("💡 提示：安装 rich 库可获得更好的终端体验：pip install rich")

    if use_rich:
        console = Console()
        console.print()
        console.print(
            Panel.fit(
                "[bold cyan]湖湘文化 GraphRAG 多智能体问答系统[/bold cyan]\n"
                "[dim]基于 LangGraph + DeepSeek + Neo4j | v3.0[/dim]",
                border_style="cyan",
            )
        )
    else:
        print("\n" + "=" * 60)
        print("  湖湘文化 GraphRAG 多智能体问答系统 v3.0")
        print("=" * 60)

    print("📖 支持的问题类型：")
    print("  • 自然语言问答：王夫之有哪些著作？")
    print("  • 路径查询：    shortest(王夫之, 曾国藩)")
    print("  • 图谱分析：    /report")
    print("  • 退出：        quit / exit\n")

    expert = GraphRAGExpert()

    try:
        while True:
            user_input = input("🧑 请输入你的问题: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit", "q"):
                if use_rich:
                    console.print("\n[bright_black]再见！船山先生与你同行。[/bright_black]\n")
                else:
                    print("\n再见！船山先生与你同行。\n")
                break

            # 特殊指令：路径查询
            path_match = re.match(
                r"shortest\s*\(\s*(.+?)\s*,\s*(.+?)\s*\)", user_input, re.IGNORECASE
            )
            if path_match:
                name1, name2 = path_match.group(1).strip(), path_match.group(2).strip()
                if use_rich:
                    console.print(f"\n🔗 [yellow]正在查询「{name1}」→「{name2}」的历史关系路径...[/yellow]\n")
                answer = expert.query_shortest_path(name1, name2)
                if use_rich:
                    console.print(Panel(Markdown(answer), border_style="green", title="路径分析结果"))
                else:
                    print(f"\n📊 路径分析结果：\n{answer}")
                continue

            # 特殊指令：图谱报告
            if user_input.strip().lower() in ("/report", "/分析", "/analytics"):
                if use_rich:
                    console.print("\n📊 [yellow]正在生成图谱分析报告...[/yellow]\n")

                    degree_data = expert.analytics.degree_centrality(10)
                    table = Table(title="度中心性 Top 10")
                    table.add_column("类型", style="cyan")
                    table.add_column("名称", style="green")
                    table.add_column("连接数", style="yellow")
                    for item in degree_data:
                        table.add_row(item["type"], item["name"], str(item["degree"]))
                    console.print(table)

                    pr_data = expert.analytics.pagerank(10)
                    table2 = Table(title="PageRank Top 10")
                    table2.add_column("类型", style="cyan")
                    table2.add_column("名称", style="green")
                    table2.add_column("分数", style="yellow")
                    for item in pr_data:
                        score_key = "pagerank" if "pagerank" in item else "pagerank_approx"
                        table2.add_row(item["type"], item["name"], str(item[score_key]))
                    console.print()
                    console.print(table2)
                else:
                    print("\n📊 图谱分析报告：")
                    ga = GraphAnalytics()
                    for item in ga.degree_centrality(10):
                        print(f"  {item['type']} · {item['name']}: degree={item['degree']}")
                    ga.close()
                continue

            # 默认：自然语言问答
            if use_rich:
                console.print()
                with console.status("[bold green]🤖 思考中...[/bold green]"):
                    result = expert.ask(user_question=user_input, verbose=False)
                console.print(Panel(result["cypher"], border_style="blue", title="生成的 Cypher"))
                console.print(Panel(Markdown(result["answer"]), border_style="green", title="回答"))
            else:
                expert.ask(user_question=user_input, verbose=True)

    except KeyboardInterrupt:
        print("\n\n👋 再见！")
    finally:
        expert.close()


if __name__ == "__main__":
    run_cli()
