"""
Text-to-SQL Service - 核心生成引擎
整合：LLM服务 + Prompt模板 + 示例检索 + Naive Bayes分类器 + 字段注释
实现：三层查询策略（规则层 + Few-shot层 + Zero-shot层）
"""

import re
import json
from typing import Dict, List, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from .llm_service import get_llm_service
    from .prompts import PromptTemplates, CommonConstraints
    from .example_retriever import get_retriever
    from .field_comment_service import get_comment_service
except ImportError:
    from llm_service import get_llm_service
    from prompts import PromptTemplates, CommonConstraints
    from example_retriever import get_retriever
    from field_comment_service import get_comment_service


# ------------------------------------------------------------------ #
# Naive Bayes 分类器（在首次需要时懒加载训练）
# ------------------------------------------------------------------ #

class _QueryClassifier:
    """
    基于 TF-IDF + Complement Naive Bayes 的查询策略分类器。
    训练数据来自 few_shot_examples.json，通过 category/difficulty 映射策略标签。
    """

    # category → strategy 映射表
    _CATEGORY_TO_STRATEGY = {
        "simple_select": "rule",
        "simple_filter": "few_shot",
        "aggregation": "few_shot",
        "join_query": "few_shot",
        "complex": "zero_shot",
        "nested_query": "zero_shot",
        "window_function": "zero_shot",
        "ranking": "zero_shot",
        "percentage": "zero_shot",
    }

    def __init__(self, examples_path: Path):
        self._clf = None
        self._vec = None
        self._examples_path = examples_path
        self._train()

    def _map_label(self, example: Dict) -> str:
        category = example.get("category", "")
        difficulty = example.get("difficulty", "easy")
        # 默认策略
        strategy = self._CATEGORY_TO_STRATEGY.get(category, "few_shot")
        # 难度为 hard 且尚未归为 zero_shot 的，提升到 zero_shot
        if difficulty == "hard" and strategy == "few_shot":
            strategy = "zero_shot"
        # 极短的 simple_select 才用规则层
        if strategy == "rule" and len(example.get("query", "")) > 12:
            strategy = "few_shot"
        return strategy

    def _train(self):
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.naive_bayes import ComplementNB
            import jieba

            if not self._examples_path.exists():
                return

            with open(self._examples_path, "r", encoding="utf-8") as f:
                examples = json.load(f)

            texts, labels = [], []
            for ex in examples:
                query = ex.get("query", "")
                keywords = " ".join(ex.get("keywords", []))
                # 中文分词后拼接
                tokens = " ".join(jieba.cut(query + " " + keywords))
                texts.append(tokens)
                labels.append(self._map_label(ex))

            if len(set(labels)) < 2:
                return  # 训练集类别不足，回退到规则分类

            self._vec = TfidfVectorizer(analyzer="word", min_df=1)
            X = self._vec.fit_transform(texts)
            self._clf = ComplementNB()
            self._clf.fit(X, labels)
            print(f"✅ 查询分类器训练完成，样本数: {len(texts)}")
        except Exception as e:
            print(f"⚠️ 分类器训练失败，回退到规则分类: {e}")

    def predict(self, query: str) -> str:
        if self._clf is None or self._vec is None:
            return self._rule_fallback(query)
        try:
            import jieba
            tokens = " ".join(jieba.cut(query))
            X = self._vec.transform([tokens])
            return self._clf.predict(X)[0]
        except Exception:
            return self._rule_fallback(query)

    @staticmethod
    def _rule_fallback(query: str) -> str:
        """分类器不可用时的兜底规则"""
        q = query.lower()
        complex_kws = ["排名", "top", "前", "最高", "最低", "占比", "百分比", "窗口", "rank"]
        if any(kw in q for kw in complex_kws):
            return "zero_shot"
        agg_kws = ["统计", "计算", "总", "平均", "最大", "最小", "求和", "count", "sum", "avg"]
        if any(kw in q for kw in agg_kws):
            return "few_shot"
        simple_kws = ["所有", "全部", "查询", "显示"]
        if any(kw in q for kw in simple_kws) and len(query) < 15:
            return "rule"
        return "few_shot"


# ------------------------------------------------------------------ #
# 主服务
# ------------------------------------------------------------------ #

class Text2SQLService:
    """Text-to-SQL 核心服务"""

    def __init__(self):
        self.llm = get_llm_service()
        self.retriever = get_retriever()
        self.prompt_builder = PromptTemplates()
        self.comment_service = get_comment_service()

        # 懒加载分类器（需要 few_shot_examples.json 路径）
        examples_path = (
            Path(__file__).parent.parent.parent / "data" / "few_shot_examples.json"
        )
        self._classifier = _QueryClassifier(examples_path)

    # ------------------------------------------------------------------ #
    # 分类
    # ------------------------------------------------------------------ #

    def _classify_query(self, query: str) -> Dict:
        strategy = self._classifier.predict(query)
        complexity_map = {"rule": "simple", "few_shot": "medium", "zero_shot": "complex"}
        return {
            "strategy": strategy,
            "category": "unknown",
            "complexity": complexity_map.get(strategy, "medium")
        }

    # ------------------------------------------------------------------ #
    # 字段注释（按需生成）
    # ------------------------------------------------------------------ #

    def _get_comments(self, datasource_id: Optional[str], schema: List[Dict]) -> Dict:
        if not datasource_id:
            return {}
        try:
            return self.comment_service.generate_for_schema(
                datasource_id=datasource_id,
                schema=schema,
                llm_service=self.llm
            )
        except Exception as e:
            print(f"⚠️ 获取字段注释失败: {e}")
            return {}

    # ------------------------------------------------------------------ #
    # 三层生成策略
    # ------------------------------------------------------------------ #

    def _generate_by_rule(self, query: str, schema: List[Dict]) -> Dict:
        if not schema:
            return {"sql": "", "success": False, "error": "Schema 为空", "strategy": "rule"}

        table_name = schema[0].get("table_name", "orders")
        if re.search(r'(所有|全部|查询)', query):
            sql = f"SELECT * FROM {table_name} LIMIT 100;"
            return {
                "sql": sql,
                "raw_response": sql,
                "success": True,
                "error": None,
                "strategy": "rule",
                "stats": {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0, "duration_ms": 0}
            }
        return self._generate_by_few_shot(query, schema)

    def _generate_by_few_shot(
        self, query: str, schema: List[Dict],
        category: Optional[str] = None,
        comments: Optional[Dict] = None
    ) -> Dict:
        examples = self.retriever.retrieve(query=query, top_k=3, category=category)
        if not examples:
            print("警告：未找到相关示例，降级到 Zero-shot")
            return self._generate_by_zero_shot(query, schema, comments=comments)

        schema_text = self.prompt_builder.format_schema(schema, comments)
        prompt = self.prompt_builder.build_few_shot_prompt(
            user_query=query,
            schema=schema_text,
            examples=examples,
            constraints=CommonConstraints.SECURITY
        )
        result = self.llm.generate(prompt=prompt, temperature=0.1, max_tokens=500)
        result["strategy"] = "few_shot"
        result["examples_used"] = len(examples)
        return result

    def _generate_by_zero_shot(
        self, query: str, schema: List[Dict],
        comments: Optional[Dict] = None
    ) -> Dict:
        schema_text = self.prompt_builder.format_schema(schema, comments)
        prompt = self.prompt_builder.build_zero_shot_prompt(
            user_query=query,
            schema=schema_text,
            constraints=CommonConstraints.SECURITY
        )
        result = self.llm.generate(prompt=prompt, temperature=0.2, max_tokens=800)
        result["strategy"] = "zero_shot"
        result["examples_used"] = 0
        return result

    # ------------------------------------------------------------------ #
    # 公共接口
    # ------------------------------------------------------------------ #

    def generate_sql(
        self,
        query: str,
        schema: List[Dict],
        force_strategy: Optional[str] = None,
        datasource_id: Optional[str] = None
    ) -> Dict:
        """
        生成 SQL（主入口）。
        datasource_id: 可选，提供后自动获取字段注释并注入 Prompt。
        """
        if not query or not query.strip():
            return {"sql": "", "success": False, "error": "查询不能为空", "strategy": "none"}
        if not schema:
            return {"sql": "", "success": False, "error": "Schema 不能为空", "strategy": "none"}

        # 按需获取字段注释
        comments = self._get_comments(datasource_id, schema)

        strategy = force_strategy or self._classify_query(query)["strategy"]

        if strategy == "rule":
            return self._generate_by_rule(query, schema)
        elif strategy == "few_shot":
            return self._generate_by_few_shot(query, schema, comments=comments)
        elif strategy == "zero_shot":
            return self._generate_by_zero_shot(query, schema, comments=comments)
        else:
            return {"sql": "", "success": False,
                    "error": f"未知策略: {strategy}", "strategy": "none"}

    def batch_generate(
        self,
        queries: List[str],
        schema: List[Dict],
        datasource_id: Optional[str] = None,
        max_workers: int = 4
    ) -> List[Dict]:
        """并发批量生成 SQL（ThreadPoolExecutor）"""
        results = [None] * len(queries)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(self.generate_sql, q, schema, None, datasource_id): i
                for i, q in enumerate(queries)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    results[idx] = {
                        "sql": "", "success": False,
                        "error": str(e), "strategy": "none"
                    }

        return results

    def interpret_results(
        self,
        user_query: str,
        columns: List[str],
        data: List[Dict],
        max_rows: int = 10
    ) -> Dict:
        """对查询结果进行业务解读"""
        try:
            sample_data = data[:max_rows]
            data_text = "，".join(columns) + "\n"
            for row in sample_data:
                data_text += "，".join([str(row.get(col, "")) for col in columns]) + "\n"
            if len(data) > max_rows:
                data_text += f"（仅展示前 {max_rows} 行，共 {len(data)} 行）\n"

            prompt = f"""你是一个数据分析助手。用户提出了一个数据查询，请用1-3句简洁的中文，从业务角度解读查询结果。

用户的查询需求：{user_query}

查询结果：
{data_text}

要求：
1. 只输出解读文字，不要输出任何其他内容
2. 从业务角度解读数据，而不是描述数据格式
3. 如果数据有明显的规律或异常，请指出
4. 控制在3句话以内，简洁明了"""

            result = self.llm.generate(prompt=prompt, temperature=0.3, max_tokens=200)
            if result["success"]:
                return {"success": True, "interpretation": result["sql"].strip(), "error": None}
            return {"success": False, "interpretation": "", "error": result.get("error", "解读失败")}

        except Exception as e:
            return {"success": False, "interpretation": "", "error": str(e)}


# ------------------------------------------------------------------ #
# 单例
# ------------------------------------------------------------------ #

_text2sql_service = None


def get_text2sql_service() -> Text2SQLService:
    global _text2sql_service
    if _text2sql_service is None:
        _text2sql_service = Text2SQLService()
    return _text2sql_service


if __name__ == "__main__":
    service = Text2SQLService()
    schema = [{
        "table_name": "orders",
        "columns": [
            {"name": "InvoiceNo", "type": "TEXT"},
            {"name": "Quantity", "type": "INTEGER"},
            {"name": "UnitPrice", "type": "REAL"},
            {"name": "Country", "type": "TEXT"}
        ]
    }]
    for q in ["查询所有订单", "统计每个国家的订单数量", "查询销售额最高的前10个商品"]:
        r = service.generate_sql(q, schema)
        status = "✅" if r["success"] else "❌"
        print(f"{status} [{r['strategy']}] {q}")
        if r["success"]:
            print(f"   SQL: {r['sql']}")
