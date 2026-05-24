import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()


def clear_entire_database():
    print("🧹 正在连接 Neo4j 数据库准备执行清仓操作...")
    uri = os.getenv("NEO4J_URI", "bolt://localhost:8687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "12345678")

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            # 执行终极清空命令
            session.run("MATCH (n) DETACH DELETE n")
        driver.close()
        print("✨ [清空成功] 本地 Neo4j 数据库已恢复出厂设置，目前一片空白！")
    except Exception as e:
        print(f"❌ 清空数据库失败，请检查 Docker 或密码配置: {e}")


if __name__ == "__main__":
    clear_entire_database()