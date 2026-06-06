"""
向量数据库入库引擎 v1.0：
将 data/clean_txt/ 中的清洗文本分块后存入 ChromaDB，
为 HM-RAG 系统的向量检索层提供数据支撑。
"""
import os
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
CLEAN_TXT_DIR = ROOT_DIR / "data" / "clean_txt"
CHROMA_DIR = ROOT_DIR / "chroma_data"

# 人物/概念名称映射：文件名 -> 用于元数据
ENTITY_TYPE_MAP = {
    "王夫之": "人物",
    "周敦颐": "人物",
    "曾国藩": "人物",
    "左宗棠": "人物",
    "魏源": "人物",
    "谭嗣同": "人物",
    "黄兴": "人物",
    "蔡锷": "人物",
    "毛泽东": "人物",
    "岳麓书院": "地点",
    "湘军": "概念",
    "经世致用": "概念",
}


def chunk_text(text: str, max_length: int = 500, overlap: int = 100) -> list[dict]:
    """将文本按段落切分为带重叠的块。

    Args:
        text: 原始文本。
        max_length: 每块最大字符数。
        overlap: 块之间的重叠字符数。

    Returns:
        包含 chunk_text 和 chunk_index 的字典列表。
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) > max_length and current_chunk:
            chunks.append(current_chunk.strip())
            # 保留尾部 overlap 字符作为下一块的开头
            if overlap > 0 and len(current_chunk) > overlap:
                current_chunk = current_chunk[-overlap:] + "\n" + para
            else:
                current_chunk = para
        else:
            current_chunk = current_chunk + "\n" + para if current_chunk else para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return [{"chunk_text": c, "chunk_index": i} for i, c in enumerate(chunks)]


def load_all_clean_texts() -> list[dict]:
    """加载所有清洗文本，返回带元数据的文档列表。"""
    documents = []

    if not CLEAN_TXT_DIR.exists():
        print(f"❌ 清洗文本目录不存在: {CLEAN_TXT_DIR}")
        print("   请先运行: python tools/clean_dataset.py")
        return documents

    # 需要跳过的文件（有更新版本替代）
    SKIP_FILES = {"wangfuzhi_baike.txt"}

    for f in sorted(CLEAN_TXT_DIR.glob("*.txt")):
        if f.name in SKIP_FILES:
            print(f"  ⏭️ 跳过旧文件: {f.name}")
            continue
        text = f.read_text(encoding="utf-8").strip()
        if len(text) < 50:
            print(f"  ⚠️ 跳过过短文件: {f.name} ({len(text)} 字)")
            continue

        entity_name = f.stem  # 文件名即实体名
        entity_type = ENTITY_TYPE_MAP.get(entity_name, "未知")
        chunks = chunk_text(text)

        for chunk in chunks:
            doc_id = f"{entity_name}_{chunk['chunk_index']:03d}"
            documents.append({
                "id": doc_id,
                "document": chunk["chunk_text"],
                "metadata": {
                    "source": f.name,
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "chunk_index": chunk["chunk_index"],
                    "char_count": len(chunk["chunk_text"]),
                },
            })

        print(f"  📄 {f.name}: {len(chunks)} 块 ({entity_name}, {entity_type})")

    return documents


def ingest_to_chromadb(documents: list[dict], collection_name: str = "huxiang_spirit"):
    """将文档列表批量写入 ChromaDB。"""
    import chromadb

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # 如果已存在同名集合，先删除再重建（确保数据一致性）
    try:
        client.delete_collection(name=collection_name)
        print(f"  🗑️ 已删除旧集合: {collection_name}")
    except Exception:
        pass

    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # ChromaDB 的 upsert 单次最多处理 5461 条，分批处理
    batch_size = 500
    total = len(documents)

    for i in range(0, total, batch_size):
        batch = documents[i : i + batch_size]
        collection.upsert(
            ids=[doc["id"] for doc in batch],
            documents=[doc["document"] for doc in batch],
            metadatas=[doc["metadata"] for doc in batch],
        )
        progress = min(i + batch_size, total)
        print(f"  ✅ 已入库 {progress}/{total} 条")

    print(f"\n🎉 ChromaDB 入库完成！集合: {collection_name}，共 {collection.count()} 条记录")
    print(f"   存储路径: {CHROMA_DIR}")
    return collection


def main():
    print("=" * 60)
    print("🚀 向量数据库入库引擎 v1.0 启动")
    print("=" * 60)

    print(f"\n📂 加载清洗文本: {CLEAN_TXT_DIR}")
    documents = load_all_clean_texts()

    if not documents:
        print("❌ 没有可用的文档，请先运行爬虫和清洗脚本。")
        return

    print(f"\n📊 共加载 {len(documents)} 个文档块")
    print(f"\n💾 开始写入 ChromaDB...")
    collection = ingest_to_chromadb(documents)

    # 验证：做一个简单的查询测试
    print(f"\n🔍 验证查询测试...")
    test_results = collection.query(
        query_texts=["王夫之的思想是什么"],
        n_results=3,
    )
    if test_results["documents"]:
        for i, doc in enumerate(test_results["documents"][0]):
            meta = test_results["metadatas"][0][i]
            print(f"  [{i+1}] 来源: {meta.get('entity_name', '?')} | 相似度距离: {test_results['distances'][0][i]:.4f}")
            print(f"      内容: {doc[:80]}...")

    print(f"\n{'='*60}")
    print("✅ 全部完成！向量数据库已就绪。")
    print("=" * 60)


if __name__ == "__main__":
    main()
