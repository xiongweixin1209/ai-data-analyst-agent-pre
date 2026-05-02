"""
Example Retriever - Few-shot示例检索服务
功能：基于jieba中文分词的关键词相似度检索，附带倒排索引加速
"""

import json
from typing import List, Dict, Optional
from pathlib import Path

import jieba
jieba.setLogLevel(20)  # 关闭jieba的INFO日志


def _tokenize(text: str) -> set:
    """使用jieba对中文文本分词，返回词集合"""
    return set(jieba.cut(text.lower()))


class ExampleRetriever:
    """Few-shot示例检索器"""

    def __init__(self, examples_path: str = None):
        if examples_path is None:
            current_dir = Path(__file__).parent
            project_root = current_dir.parent.parent
            examples_path = project_root / "data" / "few_shot_examples.json"

        self.examples_path = Path(examples_path)
        self.examples = self._load_examples()
        self._inverted_index = self._build_inverted_index()

    def _load_examples(self) -> List[Dict]:
        try:
            if not self.examples_path.exists():
                print(f"警告：示例文件不存在: {self.examples_path}")
                return []
            with open(self.examples_path, 'r', encoding='utf-8') as f:
                examples = json.load(f)
            print(f"✅ 成功加载 {len(examples)} 个示例")
            return examples
        except Exception as e:
            print(f"❌ 加载示例失败: {str(e)}")
            return []

    def _build_inverted_index(self) -> Dict[str, List[int]]:
        """构建关键词→示例索引的倒排索引，避免每次全量扫描"""
        index: Dict[str, List[int]] = {}
        for i, example in enumerate(self.examples):
            # 索引keyword字段
            for kw in example.get("keywords", []):
                for token in _tokenize(kw):
                    index.setdefault(token, []).append(i)
            # 索引query文本
            for token in _tokenize(example.get("query", "")):
                index.setdefault(token, []).append(i)
        return index

    def _calculate_similarity(self, query: str, example: Dict) -> float:
        """
        计算查询与示例的相似度（基于jieba分词）
        权重：关键词字段匹配 70%，查询文本匹配 30%
        """
        query_tokens = _tokenize(query)
        if not query_tokens:
            return 0.0

        example_kw_tokens = set()
        for kw in example.get("keywords", []):
            example_kw_tokens.update(_tokenize(kw))
        example_query_tokens = _tokenize(example.get("query", ""))

        kw_matches = len(query_tokens & example_kw_tokens)
        query_matches = len(query_tokens & example_query_tokens)

        keyword_score = (kw_matches / len(query_tokens)) * 0.7
        query_score = (query_matches / len(query_tokens)) * 0.3
        return keyword_score + query_score

    def retrieve(
            self,
            query: str,
            top_k: int = 3,
            category: Optional[str] = None,
            difficulty: Optional[str] = None
    ) -> List[Dict]:
        """检索最相关的 top_k 个示例"""
        if not self.examples:
            return []

        # 用倒排索引快速缩小候选集
        query_tokens = _tokenize(query)
        candidate_indices: set = set()
        for token in query_tokens:
            candidate_indices.update(self._inverted_index.get(token, []))

        # 候选集为空时回退到全量
        if not candidate_indices:
            candidate_indices = set(range(len(self.examples)))

        candidates = [self.examples[i] for i in candidate_indices]

        if category:
            candidates = [ex for ex in candidates if ex.get("category") == category]
        if difficulty:
            candidates = [ex for ex in candidates if ex.get("difficulty") == difficulty]

        scored = [
            {"example": ex, "score": self._calculate_similarity(query, ex)}
            for ex in candidates
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return [item["example"] for item in scored[:top_k]]

    def retrieve_by_category(self, category: str, limit: int = 5) -> List[Dict]:
        return [ex for ex in self.examples if ex.get("category") == category][:limit]

    def get_categories(self) -> List[str]:
        return sorted({ex.get("category") for ex in self.examples if ex.get("category")})

    def get_statistics(self) -> Dict:
        stats = {"total_examples": len(self.examples), "categories": {}, "difficulties": {}}
        for ex in self.examples:
            cat = ex.get("category", "unknown")
            diff = ex.get("difficulty", "unknown")
            stats["categories"][cat] = stats["categories"].get(cat, 0) + 1
            stats["difficulties"][diff] = stats["difficulties"].get(diff, 0) + 1
        return stats


_retriever = None


def get_retriever(examples_path: str = None) -> ExampleRetriever:
    global _retriever
    if _retriever is None:
        _retriever = ExampleRetriever(examples_path)
    return _retriever


if __name__ == "__main__":
    retriever = ExampleRetriever()
    stats = retriever.get_statistics()
    print(f"总示例数: {stats['total_examples']}")
    for q in ["查询所有订单", "统计每个国家的订单数量", "查询销售额最高的前10个商品"]:
        examples = retriever.retrieve(q, top_k=2)
        print(f"\n查询: {q}  → 找到 {len(examples)} 个示例")
        for ex in examples:
            print(f"  {ex['query']}")
