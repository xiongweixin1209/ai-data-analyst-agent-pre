"""
SQL Optimizer - 插件式优化规则引擎
每条规则是独立的 OptimizationRule 子类，通过 RuleRegistry 注册。
新增规则只需继承基类并注册，无需修改核心逻辑。
"""

import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import sqlparse


# ------------------------------------------------------------------ #
# 基类与注册表
# ------------------------------------------------------------------ #

class OptimizationRule(ABC):
    """优化规则基类"""
    rule_type: str = ""
    severity: str = "low"

    @abstractmethod
    def check(self, sql: str, schema: Optional[List[Dict]] = None) -> Optional[Dict]:
        """
        检查规则是否触发。
        返回建议字典（触发）或 None（未触发）。
        """


class RuleRegistry:
    """规则注册表，管理所有已注册的优化规则"""

    def __init__(self):
        self._rules: List[OptimizationRule] = []

    def register(self, rule: OptimizationRule):
        self._rules.append(rule)

    def run_all(self, sql: str, schema: Optional[List[Dict]] = None) -> List[Dict]:
        results = []
        for rule in self._rules:
            suggestion = rule.check(sql, schema)
            if suggestion:
                results.append(suggestion)
        return results


_registry = RuleRegistry()


def register_rule(cls):
    """类装饰器：实例化并注册规则"""
    _registry.register(cls())
    return cls


# ------------------------------------------------------------------ #
# 辅助函数
# ------------------------------------------------------------------ #

def _extract_where(sql: str) -> str:
    m = re.search(
        r'\bWHERE\b(.*?)(?:\bGROUP BY\b|\bORDER BY\b|\bHAVING\b|\bLIMIT\b|$)',
        sql, re.IGNORECASE | re.DOTALL
    )
    return m.group(1) if m else ""


# ------------------------------------------------------------------ #
# 规则实现
# ------------------------------------------------------------------ #

@register_rule
class MissingLimitRule(OptimizationRule):
    rule_type = "missing_limit"
    severity = "medium"

    def check(self, sql, schema=None):
        if not re.search(r'\bLIMIT\b', sql, re.IGNORECASE):
            return {
                "type": self.rule_type,
                "severity": self.severity,
                "message": "建议添加 LIMIT 限制返回行数",
                "suggestion": "在查询末尾添加 LIMIT 100 或合适的数量",
                "reason": "避免返回过多数据，提升性能和减少内存占用",
                "example": f"{sql.rstrip(';')} LIMIT 100;"
            }


@register_rule
class SelectStarRule(OptimizationRule):
    rule_type = "select_star"
    severity = "low"

    def check(self, sql, schema=None):
        if re.search(r'SELECT\s+\*', sql, re.IGNORECASE):
            return {
                "type": self.rule_type,
                "severity": self.severity,
                "message": "使用了 SELECT *，建议指定具体字段",
                "suggestion": "只选择需要的字段，例如: SELECT id, name, ...",
                "reason": "减少数据传输量，提升查询效率",
                "example": "SELECT specific_column1, specific_column2 FROM table..."
            }


@register_rule
class FunctionInWhereRule(OptimizationRule):
    rule_type = "function_in_where"
    severity = "high"

    _patterns = [
        r'YEAR\s*\(', r'MONTH\s*\(', r'DAY\s*\(', r'UPPER\s*\(',
        r'LOWER\s*\(', r'SUBSTRING\s*\(', r'CONCAT\s*\(', r'STRFTIME\s*\('
    ]

    def check(self, sql, schema=None):
        where = _extract_where(sql)
        if not where:
            return None
        found = [re.match(r'(\w+)', p).group(1)
                 for p in self._patterns if re.search(p, where, re.IGNORECASE)]
        if found:
            return {
                "type": self.rule_type,
                "severity": self.severity,
                "message": f"WHERE 条件中使用了函数: {', '.join(found)}",
                "suggestion": "避免在 WHERE 字段上使用函数，会导致索引失效",
                "reason": "函数计算阻止索引使用，导致全表扫描",
                "example": "改为: WHERE date_col >= '2024-01-01' 而不是 WHERE YEAR(date_col) = 2024"
            }


@register_rule
class LeadingWildcardRule(OptimizationRule):
    rule_type = "leading_wildcard"
    severity = "high"

    def check(self, sql, schema=None):
        if re.search(r"LIKE\s+['\"]%", sql, re.IGNORECASE):
            return {
                "type": self.rule_type,
                "severity": self.severity,
                "message": "LIKE 使用了前导通配符 '%pattern'",
                "suggestion": "避免使用前导通配符，改用 'pattern%' 或全文搜索",
                "reason": "前导通配符无法使用索引，导致全表扫描",
                "example": "WHERE col LIKE 'prefix%' 代替 WHERE col LIKE '%suffix'"
            }


@register_rule
class OrConditionsRule(OptimizationRule):
    rule_type = "or_conditions"
    severity = "medium"

    def check(self, sql, schema=None):
        where = _extract_where(sql)
        if where and re.search(r'\bOR\b', where, re.IGNORECASE):
            return {
                "type": self.rule_type,
                "severity": self.severity,
                "message": "查询中使用了 OR 条件",
                "suggestion": "考虑使用 UNION 或 IN 子句代替多个 OR",
                "reason": "OR 条件可能导致索引失效或效率低下",
                "example": "WHERE id IN (1, 2, 3) 代替 WHERE id = 1 OR id = 2 OR id = 3"
            }


@register_rule
class JoinWithoutOnRule(OptimizationRule):
    rule_type = "join_without_on"
    severity = "high"

    def check(self, sql, schema=None):
        if re.search(r'\bJOIN\b', sql, re.IGNORECASE):
            if not re.search(r'\bON\b', sql, re.IGNORECASE):
                return {
                    "type": self.rule_type,
                    "severity": self.severity,
                    "message": "检测到 JOIN 但可能缺少 ON 条件",
                    "suggestion": "确保所有 JOIN 都有明确的 ON 条件",
                    "reason": "缺少 JOIN 条件会产生笛卡尔积，严重影响性能",
                    "example": "FROM t1 JOIN t2 ON t1.id = t2.id"
                }


@register_rule
class CountStarRule(OptimizationRule):
    rule_type = "count_on_large_table"
    severity = "medium"

    def check(self, sql, schema=None):
        if re.search(r'COUNT\s*\(\s*\*\s*\)', sql, re.IGNORECASE) and schema:
            return {
                "type": self.rule_type,
                "severity": self.severity,
                "message": "在可能的大表上使用 COUNT(*)",
                "suggestion": "考虑使用近似计数或缓存结果",
                "reason": "在大表上 COUNT(*) 可能较慢",
                "example": "SELECT COUNT(*) FROM (SELECT 1 FROM table LIMIT 10000) 获取近似值"
            }


@register_rule
class SubqueryRule(OptimizationRule):
    rule_type = "subquery"
    severity = "low"

    def check(self, sql, schema=None):
        if re.search(r'\(\s*SELECT\b', sql, re.IGNORECASE):
            return {
                "type": self.rule_type,
                "severity": self.severity,
                "message": "查询中包含子查询",
                "suggestion": "考虑是否可以改写为 JOIN",
                "reason": "某些情况下 JOIN 比子查询更高效",
                "example": "将 WHERE id IN (SELECT ...) 改为 JOIN"
            }


@register_rule
class DistinctRule(OptimizationRule):
    rule_type = "distinct_usage"
    severity = "low"

    def check(self, sql, schema=None):
        if re.search(r'\bDISTINCT\b', sql, re.IGNORECASE):
            return {
                "type": self.rule_type,
                "severity": self.severity,
                "message": "使用了 DISTINCT 去重",
                "suggestion": "确认是否必须去重，考虑在数据源层面保证唯一性",
                "reason": "DISTINCT 需要额外的排序和比较操作",
                "example": "如果数据本身唯一，可以移除 DISTINCT"
            }


# ------------------------------------------------------------------ #
# 主优化器（薄壳，委托给注册表）
# ------------------------------------------------------------------ #

class SQLOptimizer:
    """SQL 优化器，通过规则注册表运行所有检查"""

    def analyze(self, sql: str, schema: Optional[List[Dict]] = None) -> Dict:
        suggestions = _registry.run_all(sql, schema)
        severity = self._overall_severity(suggestions)
        return {
            "optimizable": len(suggestions) > 0,
            "suggestions": suggestions,
            "severity": severity,
            "estimated_improvement": self._estimate(suggestions),
            "suggestion_count": len(suggestions)
        }

    @staticmethod
    def _overall_severity(suggestions: List[Dict]) -> str:
        if not suggestions:
            return "none"
        score = {"low": 1, "medium": 2, "high": 3}
        mx = max(score.get(s["severity"], 0) for s in suggestions)
        return "high" if mx >= 3 else ("medium" if mx >= 2 else "low")

    @staticmethod
    def _estimate(suggestions: List[Dict]) -> str:
        if not suggestions:
            return "无需优化"
        high = sum(1 for s in suggestions if s["severity"] == "high")
        med = sum(1 for s in suggestions if s["severity"] == "medium")
        if high >= 2:
            return "显著改善（50%+）"
        if high == 1:
            return "较大改善（20-50%）"
        if med >= 2:
            return "中等改善（10-20%）"
        return "轻微改善（<10%）"


_optimizer: Optional[SQLOptimizer] = None


def get_optimizer() -> SQLOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = SQLOptimizer()
    return _optimizer


if __name__ == "__main__":
    opt = get_optimizer()
    cases = [
        "SELECT * FROM orders WHERE YEAR(order_date) = 2024 OR country LIKE '%United%'",
        "SELECT id, name FROM users WHERE id = 123 LIMIT 100;",
        "SELECT COUNT(*) FROM orders WHERE country = 'UK';",
        "SELECT * FROM t1 JOIN t2 LIMIT 10;",
    ]
    for sql in cases:
        r = opt.analyze(sql)
        print(f"SQL: {sql[:60]}...")
        print(f"  严重程度: {r['severity']}  建议数: {r['suggestion_count']}")
        for s in r["suggestions"]:
            print(f"  [{s['severity'].upper()}] {s['message']}")
        print()
