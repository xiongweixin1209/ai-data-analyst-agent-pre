"""
RAG Retriever - Embedding 检索 + Hybrid 融合
============================================
基于 Ollama embedding API(nomic-embed-text)给 few-shot 示例库做语义检索。
跟原 jieba 倒排索引并存:
  - jieba    擅长精确字面匹配(SQL 关键字、数字、ID)
  - embedding擅长语义匹配(同义词,例如"营业额"匹配"销售额")
  - Hybrid   用 RRF (Reciprocal Rank Fusion) 融合两路,取长补短

启动时一次性预计算 120 条示例的 embedding,缓存到磁盘
(backend/data/embeddings_cache.pkl)。如果示例库内容变了(hash 不一致),
自动重算。

为什么用 Ollama embedding API 而不引入 sentence-transformers:
  - 不增加 PyTorch 这种 ~2GB 的重依赖
  - 跟现有 LLM 调用栈完全一致,部署上只多一个 ollama pull
  - 本地 7B 模型 + 本地 embedding,完全离线
"""

from __future__ import annotations

import hashlib
import json
import pickle
import time
from pathlib import Path
from typing import Optional

import numpy as np
import requests

try:
    from .example_retriever import ExampleRetriever
except ImportError:
    from example_retriever import ExampleRetriever


# 默认 embedding 模型(可被 settings 覆盖)
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"

# 缓存文件:跟 app.db 同目录,backend/data/
_CACHE_DIR = Path(__file__).parent.parent / "data"
_CACHE_PATH = _CACHE_DIR / "embeddings_cache.pkl"

# RRF 融合常数(经典值 60,Cormack 2009)
_RRF_K = 60


# ============================================================
# Embedding 检索器
# ============================================================

class EmbeddingRetriever:
    """基于 Ollama embedding 的语义检索器,带磁盘缓存"""

    def __init__(
        self,
        examples_path: Optional[Path] = None,
        model: str = DEFAULT_EMBEDDING_MODEL,
        ollama_base_url: str = "http://localhost:11434",
        cache_path: Path = _CACHE_PATH,
    ):
        if examples_path is None:
            project_root = Path(__file__).parent.parent.parent
            examples_path = project_root / "data" / "few_shot_examples.json"
        self.examples_path = Path(examples_path)
        self.model = model
        self.ollama_url = ollama_base_url.rstrip("/")
        self.cache_path = Path(cache_path)

        # 加载示例
        self.examples: list[dict] = self._load_examples()

        # 加载或重算 embedding
        self.embeddings: Optional[np.ndarray] = None
        self._available = False
        self._init_embeddings()

    def _load_examples(self) -> list[dict]:
        if not self.examples_path.exists():
            print(f"⚠️ 示例文件不存在: {self.examples_path}")
            return []
        with open(self.examples_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _examples_hash(self) -> str:
        """对示例库内容取 hash,用于检测变化"""
        content = json.dumps(self.examples, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _embed_text(self, text: str) -> Optional[np.ndarray]:
        """调 Ollama embedding API"""
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=30,
            )
            if resp.status_code != 200:
                return None
            emb = resp.json().get("embedding")
            return np.array(emb, dtype=np.float32) if emb else None
        except Exception as e:
            print(f"⚠️ embedding 调用失败: {e}")
            return None

    def _example_text(self, ex: dict) -> str:
        """把示例转成 embedding 用的文本(query + keywords 串起来)"""
        parts = [ex.get("query", "")]
        kws = ex.get("keywords", [])
        if kws:
            parts.append(" ".join(kws))
        return " | ".join(parts)

    def _init_embeddings(self) -> None:
        """启动时:命中缓存就加载,否则全量计算并缓存"""
        if not self.examples:
            print("⚠️ EmbeddingRetriever: 示例库为空,跳过")
            return

        current_hash = self._examples_hash()

        # 试读缓存
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "rb") as f:
                    cached = pickle.load(f)
                if (
                    cached.get("model") == self.model
                    and cached.get("hash") == current_hash
                    and cached.get("count") == len(self.examples)
                ):
                    self.embeddings = cached["embeddings"]
                    self._available = True
                    print(
                        f"✅ EmbeddingRetriever: 命中缓存 ({len(self.examples)} 条,"
                        f"维度 {self.embeddings.shape[1]}, model={self.model})"
                    )
                    return
                else:
                    print(
                        f"ℹ️ EmbeddingRetriever: 缓存不匹配(model/hash/count 变了),重算"
                    )
            except Exception as e:
                print(f"⚠️ EmbeddingRetriever: 缓存损坏,重算: {e}")

        # 全量计算
        print(
            f"📌 EmbeddingRetriever: 预计算 {len(self.examples)} 条示例的 embedding"
            f"(model={self.model})..."
        )
        t0 = time.time()
        embeddings: list[np.ndarray] = []
        for i, ex in enumerate(self.examples, 1):
            text = self._example_text(ex)
            emb = self._embed_text(text)
            if emb is None:
                print(
                    f"❌ EmbeddingRetriever: 第 {i} 条 embedding 失败,放弃整体初始化"
                )
                self._available = False
                return
            embeddings.append(emb)
            if i % 30 == 0:
                print(f"   进度 {i}/{len(self.examples)}")

        self.embeddings = np.stack(embeddings)
        self._available = True

        # 写缓存
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "wb") as f:
                pickle.dump(
                    {
                        "model": self.model,
                        "hash": current_hash,
                        "count": len(self.examples),
                        "embeddings": self.embeddings,
                    },
                    f,
                )
            print(
                f"✅ EmbeddingRetriever: 完成 ({time.time() - t0:.1f}s),"
                f"缓存到 {self.cache_path}"
            )
        except Exception as e:
            print(f"⚠️ EmbeddingRetriever: 缓存写入失败: {e}")

    @property
    def available(self) -> bool:
        return self._available and self.embeddings is not None

    def search(
        self, query: str, top_k: int = 10
    ) -> list[tuple[dict, float]]:
        """返回 (example, score) 列表,按 cosine 相似度降序"""
        if not self.available:
            return []
        q_emb = self._embed_text(query)
        if q_emb is None:
            return []

        # cosine similarity: dot(a, b) / (||a|| * ||b||)
        norms_db = np.linalg.norm(self.embeddings, axis=1)
        norm_q = np.linalg.norm(q_emb)
        if norm_q == 0:
            return []
        dots = self.embeddings @ q_emb
        sims = dots / (norms_db * norm_q + 1e-9)

        # top_k by score desc
        top_indices = np.argsort(-sims)[:top_k]
        return [(self.examples[i], float(sims[i])) for i in top_indices]


# ============================================================
# Hybrid 检索器:RRF 融合 embedding + jieba
# ============================================================

class HybridRetriever:
    """RRF 融合 EmbeddingRetriever + 现有 jieba ExampleRetriever。

    enable_embedding=False(默认)时只用 jieba,不初始化 embedding,
    避免 8 分钟的首次预计算开销 + 每次查询 ~4s 的额外延迟。

    任何一路挂掉都能降级到另一路单跑(只要 jieba 还在)。
    """

    def __init__(
        self,
        examples_path: Optional[Path] = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        ollama_base_url: str = "http://localhost:11434",
        enable_embedding: bool = False,
    ):
        # jieba 总是有
        self.jieba_retriever = ExampleRetriever(
            str(examples_path) if examples_path else None
        )
        # embedding 按 flag 决定
        self.embedding_retriever: Optional[EmbeddingRetriever] = None
        if enable_embedding:
            self.embedding_retriever = EmbeddingRetriever(
                examples_path=examples_path,
                model=embedding_model,
                ollama_base_url=ollama_base_url,
            )
        else:
            print(
                "ℹ️ HybridRetriever: embedding 路径未启用(jieba-only 模式)。"
                "如需启用同义词检索,设置环境变量 ENABLE_RAG=true"
            )

    @property
    def embedding_available(self) -> bool:
        return self.embedding_retriever is not None and self.embedding_retriever.available

    # 透传给 jieba 层(兼容原 ExampleRetriever API,/examples/stats 等端点会用)
    def get_statistics(self) -> dict:
        stats = self.jieba_retriever.get_statistics()
        stats["embedding_available"] = self.embedding_available
        if self.embedding_available:
            stats["embedding_dim"] = int(self.embedding_retriever.embeddings.shape[1])
            stats["embedding_model"] = self.embedding_retriever.model
        return stats

    def get_categories(self) -> list[str]:
        return self.jieba_retriever.get_categories()

    def retrieve_by_category(self, category: str, limit: int = 5) -> list[dict]:
        return self.jieba_retriever.retrieve_by_category(category, limit)

    # 暴露底层 examples 列表,便于一些代码直接遍历
    @property
    def examples(self) -> list[dict]:
        return self.jieba_retriever.examples

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        candidate_pool: int = 10,
    ) -> list[dict]:
        """RRF 融合两路检索,返回 top_k 示例(裸 dict 列表,跟原 jieba 兼容)"""

        # 路径 A:jieba(原有逻辑)
        jieba_top = self.jieba_retriever.retrieve(
            query=query,
            top_k=candidate_pool,
            category=category,
            difficulty=difficulty,
        )

        # 路径 B:embedding(可能不可用,可用就跑)
        embedding_top: list[dict] = []
        if self.embedding_available:
            embedding_results = self.embedding_retriever.search(
                query, top_k=candidate_pool
            )
            # 应用 category / difficulty 过滤(embedding 检索本身不过滤,这里补)
            for ex, _score in embedding_results:
                if category and ex.get("category") != category:
                    continue
                if difficulty and ex.get("difficulty") != difficulty:
                    continue
                embedding_top.append(ex)

        # 如果只有 jieba 可用,直接退化到 jieba 的 top_k
        if not embedding_top:
            return jieba_top[:top_k]

        # RRF 融合
        # 用示例的 (query + sql) 作为去重 key
        def _key(ex: dict) -> str:
            return f"{ex.get('query','')}||{ex.get('sql','')[:100]}"

        rrf_scores: dict[str, float] = {}
        example_map: dict[str, dict] = {}

        for rank, ex in enumerate(jieba_top):
            k = _key(ex)
            rrf_scores[k] = rrf_scores.get(k, 0.0) + 1.0 / (_RRF_K + rank)
            example_map[k] = ex

        for rank, ex in enumerate(embedding_top):
            k = _key(ex)
            rrf_scores[k] = rrf_scores.get(k, 0.0) + 1.0 / (_RRF_K + rank)
            example_map[k] = ex

        # 按 RRF 分数降序排
        sorted_keys = sorted(rrf_scores.keys(), key=lambda k: -rrf_scores[k])
        return [example_map[k] for k in sorted_keys[:top_k]]


# ============================================================
# 单例
# ============================================================

_hybrid_retriever: Optional[HybridRetriever] = None


def get_hybrid_retriever() -> HybridRetriever:
    """工厂函数,按 settings.ENABLE_RAG 决定是否启用 embedding 路径。"""
    global _hybrid_retriever
    if _hybrid_retriever is None:
        # 读 settings.ENABLE_RAG。如果 config 不可用(脚本独立运行场景),
        # 退化到读环境变量 ENABLE_RAG。
        enable_embedding = False
        try:
            from config import settings
            enable_embedding = bool(getattr(settings, "ENABLE_RAG", False))
        except Exception:
            import os
            enable_embedding = os.getenv("ENABLE_RAG", "").lower() in ("1", "true", "yes")
        _hybrid_retriever = HybridRetriever(enable_embedding=enable_embedding)
    return _hybrid_retriever


# ============================================================
# Smoke Test
# ============================================================

if __name__ == "__main__":
    import sys, io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=" * 60)
    print("RAG Retriever Smoke Test")
    print("=" * 60)

    retriever = get_hybrid_retriever()

    print()
    print(f"jieba 可用:    True (always)")
    print(f"embedding 可用: {retriever.embedding_available}")

    test_queries = [
        # 字面匹配场景(jieba 更强)
        "查询销售额最高的前 10 个商品",
        # 同义词场景(embedding 更强):"营业额" 同义 "销售额"
        "营业额最高的产品",
        # 口语化场景(embedding 更强)
        "哪家店卖得最好",
        # 时序场景
        "按月统计订单数量",
    ]

    for q in test_queries:
        print()
        print(f"--- Query: {q} ---")
        results = retriever.retrieve(q, top_k=3)
        for i, ex in enumerate(results, 1):
            print(f"  {i}. [{ex.get('category','?'):<20}] {ex.get('query','')[:50]}")
