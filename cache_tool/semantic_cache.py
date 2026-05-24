"""
语义缓存模块：基于向量相似度的问答结果缓存，避免重复计算。
优先使用 sentence-transformers 做语义编码，回退到字符 n-gram 相似度。
"""
import os
import json
import time
import hashlib
from typing import Any
from pathlib import Path

# ---------------------------------------------------------------------------
# 缓存数据目录
# ---------------------------------------------------------------------------
CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_FILE = CACHE_DIR / "qa_cache.json"


# ---------------------------------------------------------------------------
# 文本相似度引擎
# ---------------------------------------------------------------------------

class _NgramSimilarity:
    """基于字符 n-gram 的轻量级中文文本相似度计算（零依赖回退方案）。"""

    def __init__(self, n: int = 3):
        self.n = n

    def _ngrams(self, text: str) -> set[str]:
        t = text.lower().strip()
        return {t[i:i + self.n] for i in range(len(t) - self.n + 1)}

    def similarity(self, text1: str, text2: str) -> float:
        n1 = self._ngrams(text1)
        n2 = self._ngrams(text2)
        if not n1 or not n2:
            return 0.0
        return len(n1 & n2) / len(n1 | n2)


class _EmbeddingSimilarity:
    """使用 sentence-transformers 做语义相似度计算。"""

    def __init__(self):
        self._model = None

    @property
    def available(self) -> bool:
        try:
            import sentence_transformers  # noqa: F401
            return True
        except ImportError:
            return False

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(
                "paraphrase-multilingual-MiniLM-L12-v2",
                cache_folder=str(CACHE_DIR / "models"),
            )
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        embeddings = model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def similarity_from_embeddings(self, emb1: list[float], emb2: list[float]) -> float:
        return sum(a * b for a, b in zip(emb1, emb2))


# ---------------------------------------------------------------------------
# 语义缓存
# ---------------------------------------------------------------------------

class SemanticCache:
    """语义缓存：基于问题向量相似度匹配，命中时直接返回历史回答。

    相似度阈值默认 0.85（n-gram 模式）或 0.90（embedding 模式）。
    缓存持久化到本地 JSON 文件，最大容量 500 条。
    """

    def __init__(
        self,
        similarity_threshold: float | None = None,
        max_entries: int = 500,
    ):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # 尝试使用 embedding 引擎
        self._emb = _EmbeddingSimilarity()
        if self._emb.available:
            self._engine: _EmbeddingSimilarity | _NgramSimilarity = self._emb
            self._threshold = similarity_threshold or 0.90
            self._use_embeddings = True
        else:
            self._engine = _NgramSimilarity(n=3)
            self._threshold = similarity_threshold or 0.85
            self._use_embeddings = False

        self._max_entries = max_entries
        self._entries: list[dict[str, Any]] = []
        self._load()

    # ---- 公共 API ----

    def lookup(self, question: str) -> dict | None:
        """查找与 question 语义最相似的缓存条目。

        Returns:
            命中时返回 {"answer": str, "cypher": str, "evidence": list}，
            未命中返回 None。
        """
        if not self._entries:
            return None

        # 计算与所有缓存条目的相似度
        best_score = 0.0
        best_entry = None

        if self._use_embeddings:
            q_emb = self._engine.encode([question])[0]
            for entry in self._entries:
                score = self._engine.similarity_from_embeddings(
                    q_emb, entry["embedding"]
                )
                if score > best_score:
                    best_score = score
                    best_entry = entry
        else:
            for entry in self._entries:
                score = self._engine.similarity(question, entry["question"])
                if score > best_score:
                    best_score = score
                    best_entry = entry

        if best_score >= self._threshold and best_entry is not None:
            best_entry["_hit_score"] = best_score  # 调试用
            return {
                "answer": best_entry["answer"],
                "cypher": best_entry["cypher"],
                "evidence": best_entry["evidence"],
            }
        return None

    def store(self, question: str, answer: str, cypher: str, evidence: list) -> None:
        """将问答结果存入缓存。"""
        entry = {
            "question": question,
            "answer": answer,
            "cypher": cypher,
            "evidence": evidence,
            "timestamp": time.time(),
        }

        if self._use_embeddings:
            entry["embedding"] = self._engine.encode([question])[0]

        self._entries.append(entry)

        # 超过最大容量时淘汰最旧的
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

        self._save()

    def stats(self) -> dict[str, Any]:
        return {
            "entries": len(self._entries),
            "engine": "embeddings" if self._use_embeddings else "ngram",
            "threshold": self._threshold,
        }

    def clear(self) -> None:
        """清空所有缓存。"""
        self._entries = []
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()

    # ---- 内部 ----

    def _load(self) -> None:
        if not CACHE_FILE.exists():
            return
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            self._entries = data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            self._entries = []

    def _save(self) -> None:
        try:
            # 只保存必要字段（embedding 太大，不存到磁盘——下次启动重新计算）
            slim = []
            for e in self._entries[-self._max_entries:]:
                slim.append({
                    "question": e["question"],
                    "answer": e["answer"],
                    "cypher": e["cypher"],
                    "evidence": e["evidence"],
                    "timestamp": e["timestamp"],
                })
            CACHE_FILE.write_text(
                json.dumps(slim, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass  # 磁盘写入失败不影响功能


# ---------------------------------------------------------------------------
# 全局单例（供 rag_agent 和 web_ui 共用）
# ---------------------------------------------------------------------------

_cache_instance: SemanticCache | None = None


def get_cache() -> SemanticCache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = SemanticCache()
    return _cache_instance
