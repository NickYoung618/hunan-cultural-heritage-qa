import os
import json
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()


class HuxiangGraph:
    def __init__(self):
        uri = os.getenv("NEO4J_URI", "bolt://localhost:8687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "12345678")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def write_entities_to_graph(self, json_data: str):
        try:
            # 1. 容错处理：清理大模型可能带有的 Markdown 代码块标记
            json_data = json_data.strip()
            if json_data.startswith("```json"):
                json_data = json_data[7:]
            if json_data.endswith("```"):
                json_data = json_data[:-3]

            # 2. 解析 JSON 数据
            data = json.loads(json_data)
            entities = data.get("entities", [])
            relationships = data.get("relationships", [])

            if not entities:
                return "❌ 没有找到可用的实体数据"

            # 3. 开启数据库事务
            with self.driver.session() as session:
                # 写入节点 (这部分不变)
                # 写入节点
                for entity in entities:
                    name = entity.get("name")
                    entity_type = entity.get("type", "未知实体")
                    # 👇 1. 确保安全取出 description
                    desc_text = entity.get("description", "")

                    # 👇 2. Cypher 语句中必须有 SET n.description
                    cypher_node = f"""
                                    MERGE (n:`{entity_type}` {{name: $name}})
                                    SET n.description = $description
                                    """
                    # 👇 3. 极其关键：session.run 里必须传入 description=desc_text！
                    session.run(cypher_node, name=name, description=desc_text)

                # 写入关系 (画线) —— 👈 核心升级区
                for rel in relationships:
                    source = rel.get("source")
                    target = rel.get("target")
                    relation_type = rel.get("relation", "关联").replace(" ", "_")

                    # 1. 安全提取：把大模型辛苦抄下来的原话拿出来，如果没有就给个空字符串
                    detail_text = rel.get("detail", "")

                    # 2. Cypher 升级：利用 SET 语法，把 detail 属性挂载到关系(r)上
                    cypher_edge = f"""
                    MATCH (a {{name: $source}})
                    MATCH (b {{name: $target}})
                    MERGE (a)-[r:`{relation_type}`]->(b)
                    SET r.detail = $detail
                    """

                    # 3. 注入变量：连同 source、target 一起，把 detail_text 喂给数据库
                    session.run(cypher_edge, source=source, target=target, detail=detail_text)

            # 确保这个 return 与 with 语句同级对齐
            return f"✅ 成功写入 {len(entities)} 个节点 和 {len(relationships)} 条关系！"

        except Exception as e:
            return f"❌ 图谱入库失败: {str(e)}"


def save_to_neo4j(json_string: str) -> str:
    graph_db = HuxiangGraph()
    result = graph_db.write_entities_to_graph(json_string)
    graph_db.close()
    return result