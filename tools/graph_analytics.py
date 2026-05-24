"""
图谱分析引擎 v1.0：基于 Neo4j 的图算法分析模块。
提供最短路径查询、中心度分析等图论能力，挖掘湖湘文化图谱中的隐性知识。
"""
import os
from typing import Any
from neo4j import GraphDatabase
from neo4j.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()


class GraphAnalytics:
    """Neo4j 图谱分析器，封装常用图算法查询。"""

    def __init__(self) -> None:
        uri = os.getenv("NEO4J_URI", "bolt://localhost:8687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "12345678")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._gds_available: bool | None = None  # 延迟检测

    def close(self) -> None:
        """关闭数据库连接。"""
        self.driver.close()

    def _check_gds(self) -> bool:
        """检测 Neo4j GDS 库是否可用。"""
        if self._gds_available is None:
            try:
                with self.driver.session() as session:
                    session.run("RETURN gds.version()")
                self._gds_available = True
                print("✅ GDS 库可用，将使用原生图算法。")
            except ClientError:
                self._gds_available = False
                print("⚠️ GDS 库不可用，将回退到纯 Cypher 实现。")
        return self._gds_available

    def shortest_path(
        self, start_name: str, end_name: str, max_depth: int = 6
    ) -> list[dict[str, Any]]:
        """查询两个实体之间的最短路径，揭示历史关系链条。

        Args:
            start_name: 起点实体名称（如 "周敦颐"）。
            end_name: 终点实体名称（如 "王夫之"）。
            max_depth: 最大搜索深度，防止笛卡尔爆炸。

        Returns:
            路径列表，每条路径包含节点序列和关系序列。
        """
        cypher = """
            MATCH p = shortestPath((a)-[*..$max_depth]-(b))
            WHERE a.name = $start_name AND b.name = $end_name
            RETURN
                [node IN nodes(p) | {name: node.name, type: labels(node)[0]}] AS nodes,
                [rel IN relationships(p) | {
                    from: startNode(rel).name,
                    to: endNode(rel).name,
                    relation: type(rel)
                }] AS relationships,
                length(p) AS hops
            ORDER BY hops
            LIMIT 5
        """
        with self.driver.session() as session:
            result = session.run(
                cypher,
                start_name=start_name,
                end_name=end_name,
                max_depth=max_depth,
            )
            records = [record.data() for record in result]

        if not records:
            # 尝试双向模糊匹配
            return self._shortest_path_fuzzy(start_name, end_name, max_depth)

        return records

    def _shortest_path_fuzzy(
        self, start_name: str, end_name: str, max_depth: int = 6
    ) -> list[dict[str, Any]]:
        """模糊匹配版本：使用 CONTAINS 进行宽松搜索。"""
        cypher = """
            MATCH (a), (b)
            WHERE a.name CONTAINS $start_kw AND b.name CONTAINS $end_kw
            MATCH p = shortestPath((a)-[*..$max_depth]-(b))
            RETURN
                [node IN nodes(p) | {name: node.name, type: labels(node)[0]}] AS nodes,
                [rel IN relationships(p) | {
                    from: startNode(rel).name,
                    to: endNode(rel).name,
                    relation: type(rel)
                }] AS relationships,
                length(p) AS hops
            ORDER BY hops
            LIMIT 5
        """
        try:
            with self.driver.session() as session:
                result = session.run(
                    cypher,
                    start_kw=start_name,
                    end_kw=end_name,
                    max_depth=max_depth,
                )
                return [record.data() for record in result]
        except ClientError:
            return []

    def all_shortest_paths(
        self, start_name: str, end_name: str, max_depth: int = 6
    ) -> list[dict[str, Any]]:
        """查询两个实体之间的所有最短路径。

        Args:
            start_name: 起点实体名称。
            end_name: 终点实体名称。
            max_depth: 最大搜索深度。

        Returns:
            所有最短路径列表。
        """
        cypher = """
            MATCH p = allShortestPaths((a)-[*..$max_depth]-(b))
            WHERE a.name = $start_name AND b.name = $end_name
            RETURN
                [node IN nodes(p) | {name: node.name, type: labels(node)[0]}] AS nodes,
                [rel IN relationships(p) | {
                    from: startNode(rel).name,
                    to: endNode(rel).name,
                    relation: type(rel)
                }] AS relationships,
                length(p) AS hops
            LIMIT 10
        """
        with self.driver.session() as session:
            result = session.run(
                cypher,
                start_name=start_name,
                end_name=end_name,
                max_depth=max_depth,
            )
            return [record.data() for record in result]

    def degree_centrality(self, limit: int = 20) -> list[dict[str, Any]]:
        """基于度中心性的核心节点分析——找出关系最多的实体。

        度数越高，表示该实体在知识图谱中连接越广（隐含重要性越高）。

        Args:
            limit: 返回的 Top-N 数量。

        Returns:
            按度数降序排列的实体列表。
        """
        cypher = """
            MATCH (n)
            OPTIONAL MATCH (n)-[r]-()
            WITH n, count(r) AS degree
            WHERE degree > 0
            RETURN
                labels(n)[0] AS type,
                n.name AS name,
                degree
            ORDER BY degree DESC
            LIMIT $limit
        """
        with self.driver.session() as session:
            result = session.run(cypher, limit=limit)
            return [record.data() for record in result]

    def pagerank(self, limit: int = 20) -> list[dict[str, Any]]:
        """PageRank 中心度分析——找出图谱中的「意见领袖」。

        优先使用 Neo4j GDS 库；若不可用则回退到加权度中心性。

        Args:
            limit: 返回的 Top-N 数量。

        Returns:
            按 PageRank 分数降序排列的实体列表。
        """
        if self._check_gds():
            return self._pagerank_gds(limit)
        else:
            return self._pagerank_cypher_fallback(limit)

    def _pagerank_gds(self, limit: int = 20) -> list[dict[str, Any]]:
        """使用 GDS 库的 PageRank 算法。"""
        cypher = """
            CALL gds.graph.project(
                'huxiang_pagerank',
                '*',
                '*',
                {relationshipProperties: 'weight'}
            )
            YIELD graphName
            WITH graphName
            CALL gds.pageRank.stream(graphName, {maxIterations: 20, dampingFactor: 0.85})
            YIELD nodeId, score
            WITH gds.util.asNode(nodeId) AS n, score
            RETURN labels(n)[0] AS type, n.name AS name, round(score, 6) AS pagerank
            ORDER BY pagerank DESC
            LIMIT $limit
        """
        try:
            with self.driver.session() as session:
                # 先尝试删除旧图投影（幂等操作）
                try:
                    session.run("CALL gds.graph.drop('huxiang_pagerank', false)")
                except ClientError:
                    pass
                result = session.run(cypher, limit=limit)
                records = [record.data() for record in result]
                # 清理投影
                try:
                    session.run("CALL gds.graph.drop('huxiang_pagerank', false)")
                except ClientError:
                    pass
                return records
        except ClientError:
            return self._pagerank_cypher_fallback(limit)

    def _pagerank_cypher_fallback(self, limit: int = 20) -> list[dict[str, Any]]:
        """纯 Cypher 的加权度中心性作为 PageRank 近似。

        同时考虑出度和入度的加权总和。
        """
        cypher = """
            MATCH (n)
            OPTIONAL MATCH (n)-[r_out]->()
            OPTIONAL MATCH ()-[r_in]->(n)
            WITH n,
                count(DISTINCT r_out) AS out_degree,
                count(DISTINCT r_in) AS in_degree
            WITH n, out_degree, in_degree,
                (out_degree * 0.4 + in_degree * 0.6) AS weighted_score
            WHERE weighted_score > 0
            RETURN
                labels(n)[0] AS type,
                n.name AS name,
                out_degree,
                in_degree,
                round(weighted_score, 4) AS pagerank_approx
            ORDER BY pagerank_approx DESC
            LIMIT $limit
        """
        with self.driver.session() as session:
            result = session.run(cypher, limit=limit)
            return [record.data() for record in result]

    def betweenness_centrality(self, limit: int = 20) -> list[dict[str, Any]]:
        """介数中心性——找出图谱中的「信息桥梁」节点。

        Args:
            limit: 返回的 Top-N 数量。

        Returns:
            按介数中心性降序排列的实体列表。
        """
        cypher = """
            MATCH (n)
            WHERE NOT isEmpty([(n)-[]-() | 1])
            OPTIONAL MATCH (a)-[r1]-(n)-[r2]-(b)
            WHERE a <> b
            WITH n, count(DISTINCT [a, b]) AS bridge_count
            WHERE bridge_count > 0
            RETURN
                labels(n)[0] AS type,
                n.name AS name,
                bridge_count AS betweenness_approx
            ORDER BY betweenness_approx DESC
            LIMIT $limit
        """
        with self.driver.session() as session:
            result = session.run(cypher, limit=limit)
            return [record.data() for record in result]

    def full_report(self) -> dict[str, Any]:
        """生成一份完整的图谱分析报告。

        Returns:
            包含路径示例、Top-N 核心节点、桥梁节点的综合报告字典。
        """
        has_gds = self._check_gds()

        # 获取数据库中的人物样本用于路径展示
        sample_path = []
        with self.driver.session() as session:
            result = session.run(
                "MATCH (n:`人物`) RETURN n.name AS name LIMIT 10"
            )
            names = [r["name"] for r in result]
            if len(names) >= 2:
                sample_path = self.shortest_path(names[0], names[-1])

        report: dict[str, Any] = {
            "gds_available": has_gds,
            "degree_top10": self.degree_centrality(10),
            "pagerank_top10": self.pagerank(10),
            "betweenness_top10": self.betweenness_centrality(10),
            "sample_shortest_path": sample_path,
        }
        return report


# --- 便捷函数 ---

def query_shortest_path(start_name: str, end_name: str) -> list[dict[str, Any]]:
    """查询两个湖湘名人之间的历史关系路径。"""
    ga = GraphAnalytics()
    result = ga.shortest_path(start_name, end_name)
    ga.close()
    return result


def query_pagerank(limit: int = 20) -> list[dict[str, Any]]:
    """获取图谱 PageRank 排名。"""
    ga = GraphAnalytics()
    result = ga.pagerank(limit)
    ga.close()
    return result


def query_full_report() -> dict[str, Any]:
    """生成完整图谱分析报告。"""
    ga = GraphAnalytics()
    report = ga.full_report()
    ga.close()
    return report


if __name__ == "__main__":
    print("=" * 60)
    print("📊 湖湘文化图谱分析报告")
    print("=" * 60)

    ga = GraphAnalytics()

    # 1. 度中心性 Top 10
    print("\n🏆 【度中心性 Top 10】")
    for item in ga.degree_centrality(10):
        print(f"  {item['type']} · {item['name']}: degree={item['degree']}")

    # 2. PageRank Top 10
    print("\n📈 【PageRank Top 10】")
    for item in ga.pagerank(10):
        score_key = "pagerank" if "pagerank" in item else "pagerank_approx"
        print(f"  {item['type']} · {item['name']}: score={item[score_key]}")

    # 3. 介数中心性 Top 10
    print("\n🌉 【介数中心性（桥梁节点）Top 10】")
    for item in ga.betweenness_centrality(10):
        print(f"  {item['type']} · {item['name']}: bridge_count={item['betweenness_approx']}")

    ga.close()
    print("\n✅ 分析完成。")
