"""
Query Performance Analyzer - 查询性能分析服务（综合优化版）
功能：EXPLAIN分析、性能监控、索引建议
修复：re模块导入问题
优化：异常处理、代码健壮性
"""

import sqlite3
import time
import re  # ✅ 修复：在文件顶部导入，避免作用域问题
from typing import Dict, List, Optional
from pathlib import Path


class QueryPerformanceAnalyzer:
    """查询性能分析器"""

    def __init__(self, db_path: str):
        """
        初始化分析器

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path

        if not Path(db_path).exists():
            raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    def analyze(self, sql: str) -> Dict:
        """
        完整性能分析

        Args:
            sql: SQL语句

        Returns:
            Dict: 分析结果
        """
        result = {
            "sql": sql,
            "explain_plan": None,
            "performance_metrics": None,
            "index_suggestions": [],
            "warnings": []
        }

        try:
            # 1. EXPLAIN查询计划
            result["explain_plan"] = self._explain_query(sql)

            # 2. 性能指标（多次执行取平均）
            result["performance_metrics"] = self._measure_performance(sql, runs=3)

            # 3. 索引建议
            result["index_suggestions"] = self._suggest_indexes(sql, result["explain_plan"])

            # 4. 性能警告
            result["warnings"] = self._generate_warnings(
                result["explain_plan"],
                result["performance_metrics"]
            )
        except Exception as e:
            # ✅ 优化：添加顶层异常处理
            result["warnings"].append(f"⚠️ 分析过程出错: {str(e)}")

        return result

    def _explain_query(self, sql: str) -> Optional[Dict]:
        """
        执行EXPLAIN查询计划分析

        Args:
            sql: SQL语句

        Returns:
            Dict: 查询计划
        """
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            cursor = conn.cursor()

            # 执行EXPLAIN QUERY PLAN
            cursor.execute(f"EXPLAIN QUERY PLAN {sql}")

            # 获取结果
            plan_rows = cursor.fetchall()

            # 格式化查询计划
            plan = {
                "steps": [],
                "has_table_scan": False,
                "uses_index": False,
                "complexity": "simple"
            }

            for row in plan_rows:
                step = {
                    "id": row[0],
                    "parent": row[1],
                    "detail": row[3] if len(row) > 3 else row[2]
                }

                detail_upper = step["detail"].upper()  # ✅ 优化：转大写便于匹配

                # 检查是否是表扫描
                if "SCAN TABLE" in detail_upper:
                    plan["has_table_scan"] = True

                # 检查是否使用索引
                if "USING INDEX" in detail_upper or "SEARCH TABLE" in detail_upper:
                    plan["uses_index"] = True

                plan["steps"].append(step)

            # 判断查询复杂度
            if len(plan_rows) > 5:
                plan["complexity"] = "complex"
            elif len(plan_rows) > 2:
                plan["complexity"] = "medium"

            conn.close()

            return plan

        except Exception as e:
            return {
                "error": str(e),
                "steps": [],
                "has_table_scan": False,
                "uses_index": False,
                "complexity": "unknown"
            }

    def _measure_performance(self, sql: str, runs: int = 3) -> Dict:
        """
        测量查询性能

        Args:
            sql: SQL语句
            runs: 运行次数

        Returns:
            Dict: 性能指标
        """
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            cursor = conn.cursor()

            timings = []
            row_counts = []

            # 预热查询（首次查询会慢）
            try:
                cursor.execute(sql)
                cursor.fetchall()
            except Exception:
                pass  # ✅ 优化：预热失败不影响后续测试

            # 多次执行测量
            for _ in range(runs):
                start_time = time.time()
                cursor.execute(sql)
                rows = cursor.fetchall()
                end_time = time.time()

                timings.append((end_time - start_time) * 1000)  # 转换为毫秒
                row_counts.append(len(rows))

            conn.close()

            # 计算统计值
            avg_time = sum(timings) / len(timings)
            min_time = min(timings)
            max_time = max(timings)
            avg_rows = sum(row_counts) / len(row_counts)

            return {
                "average_time_ms": round(avg_time, 2),
                "min_time_ms": round(min_time, 2),
                "max_time_ms": round(max_time, 2),
                "row_count": int(avg_rows),
                "runs": runs,
                "performance_level": self._classify_performance(avg_time)
            }

        except Exception as e:
            return {
                "error": str(e),
                "average_time_ms": 0,
                "min_time_ms": 0,
                "max_time_ms": 0,
                "row_count": 0,
                "runs": 0,
                "performance_level": "unknown"
            }

    def _classify_performance(self, time_ms: float) -> str:
        """
        分类性能等级

        Args:
            time_ms: 执行时间（毫秒）

        Returns:
            str: 性能等级
        """
        if time_ms < 10:
            return "excellent"  # 优秀
        elif time_ms < 50:
            return "good"  # 良好
        elif time_ms < 200:
            return "fair"  # 一般
        elif time_ms < 1000:
            return "poor"  # 较差
        else:
            return "very_poor"  # 很差

    def _suggest_indexes(self, sql: str, explain_plan: Dict) -> List[Dict]:
        """
        根据查询和执行计划建议索引

        Args:
            sql: SQL语句
            explain_plan: 查询计划

        Returns:
            List[Dict]: 索引建议
        """
        suggestions = []

        if not explain_plan or explain_plan.get("error"):
            return suggestions

        try:
            # 如果有表扫描，建议创建索引
            if explain_plan.get("has_table_scan"):
                # ✅ 修复：移除了方法内的 import re，使用顶部导入的re

                # 简单提取WHERE条件中的字段
                where_match = re.search(
                    r'\bWHERE\b\s+(.*?)(?:\bGROUP BY\b|\bORDER BY\b|\bLIMIT\b|;|$)',
                    sql,
                    re.IGNORECASE | re.DOTALL
                )

                if where_match:
                    where_clause = where_match.group(1)

                    # 提取可能的字段名（简化版）
                    potential_fields = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*[=<>]', where_clause)

                    for field in set(potential_fields):
                        suggestions.append({
                            "type": "create_index",
                            "reason": "WHERE条件中的字段可能需要索引",
                            "field": field,
                            "suggestion": f"CREATE INDEX idx_{field} ON table_name({field});",
                            "expected_improvement": "减少全表扫描，提升查询速度"
                        })

            # 检查JOIN条件
            if "JOIN" in sql.upper():
                suggestions.append({
                    "type": "join_index",
                    "reason": "JOIN操作可能需要索引",
                    "suggestion": "确保JOIN条件的字段都有索引",
                    "expected_improvement": "加速表连接操作"
                })

            # 检查ORDER BY
            if "ORDER BY" in sql.upper():
                order_match = re.search(
                    r'\bORDER BY\b\s+(.*?)(?:\bLIMIT\b|;|$)',
                    sql,
                    re.IGNORECASE
                )

                if order_match:
                    suggestions.append({
                        "type": "order_index",
                        "reason": "ORDER BY字段可能需要索引",
                        "suggestion": "为排序字段创建索引",
                        "expected_improvement": "避免排序操作，直接返回有序结果"
                    })

        except Exception as e:
            # ✅ 优化：捕获异常，避免索引建议失败影响整个分析
            suggestions.append({
                "type": "error",
                "reason": f"索引建议生成失败: {str(e)}",
                "suggestion": "请检查SQL语法",
                "expected_improvement": "N/A"
            })

        return suggestions

    def _generate_warnings(
            self,
            explain_plan: Dict,
            performance_metrics: Dict
    ) -> List[str]:
        """
        生成性能警告

        Args:
            explain_plan: 查询计划
            performance_metrics: 性能指标

        Returns:
            List[str]: 警告列表
        """
        warnings = []

        try:
            # 检查表扫描
            if explain_plan and explain_plan.get("has_table_scan"):
                warnings.append("⚠️ 查询使用了全表扫描，可能影响性能")

            # 检查执行时间
            if performance_metrics and "error" not in performance_metrics:
                perf_level = performance_metrics.get("performance_level")
                avg_time = performance_metrics.get("average_time_ms", 0)

                if perf_level == "poor":
                    warnings.append(f"⚠️ 查询较慢（{avg_time:.2f}ms），建议优化")
                elif perf_level == "very_poor":
                    warnings.append(f"🚨 查询很慢（{avg_time:.2f}ms），强烈建议优化！")

            # 检查返回行数
            if performance_metrics and "error" not in performance_metrics:
                row_count = performance_metrics.get("row_count", 0)

                if row_count > 1000:
                    warnings.append(f"⚠️ 返回了大量数据（{row_count}行），建议添加LIMIT")

            # ✅ 优化：如果没有警告，添加正面反馈
            if not warnings:
                warnings.append("✅ 未发现明显的性能问题")

        except Exception as e:
            warnings.append(f"⚠️ 生成警告时出错: {str(e)}")

        return warnings

    def get_table_indexes(self, table_name: str) -> List[Dict]:
        """
        获取表的现有索引

        Args:
            table_name: 表名

        Returns:
            List[Dict]: 索引列表
        """
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            cursor = conn.cursor()

            # 获取索引列表
            cursor.execute(f"PRAGMA index_list({table_name});")
            indexes = []

            for row in cursor.fetchall():
                index_name = row[1]

                # 获取索引详情
                cursor.execute(f"PRAGMA index_info({index_name});")
                columns = [col[2] for col in cursor.fetchall()]

                indexes.append({
                    "name": index_name,
                    "columns": columns,
                    "unique": bool(row[2])
                })

            conn.close()

            return indexes

        except Exception as e:
            # ✅ 优化：返回空列表而不是抛出异常
            return []


def get_analyzer(db_path: str) -> QueryPerformanceAnalyzer:
    """获取分析器实例"""
    return QueryPerformanceAnalyzer(db_path)


# ============================================================
# 测试代码
# ============================================================
if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config import settings

    print("=" * 60)
    print("测试查询性能分析器（综合优化版）")
    print("=" * 60)

    db_path = settings.DEMO_DB_PATH

    try:
        analyzer = get_analyzer(db_path)

        # 测试用例
        test_cases = [
            {
                "name": "简单查询（有LIMIT）",
                "sql": "SELECT * FROM orders WHERE quantity > 10 LIMIT 100;"
            },
            {
                "name": "聚合查询",
                "sql": "SELECT country, COUNT(*) as cnt FROM orders GROUP BY country;"
            },
            {
                "name": "复杂查询（无LIMIT）",
                "sql": """
                    SELECT stock_code, SUM(quantity * unit_price) as total
                    FROM orders
                    WHERE country = 'United Kingdom'
                    GROUP BY stock_code
                    ORDER BY total DESC;
                """
            }
        ]

        for i, test in enumerate(test_cases, 1):
            print(f"\n【测试 {i}】{test['name']}")
            print("-" * 60)
            sql_preview = test['sql'].strip()[:80]
            print(f"SQL: {sql_preview}{'...' if len(test['sql'].strip()) > 80 else ''}")

            # 执行分析
            result = analyzer.analyze(test['sql'])

            # 显示查询计划
            if result["explain_plan"]:
                plan = result["explain_plan"]
                print(f"\n📋 查询计划:")
                print(f"   复杂度: {plan['complexity']}")
                print(f"   使用索引: {'是' if plan['uses_index'] else '否'}")
                print(f"   表扫描: {'是' if plan['has_table_scan'] else '否'}")

                if plan.get('steps'):
                    print(f"   执行步骤:")
                    for step in plan['steps']:
                        print(f"     - {step['detail']}")

            # 显示性能指标
            if result["performance_metrics"] and "error" not in result["performance_metrics"]:
                metrics = result["performance_metrics"]
                print(f"\n⏱️ 性能指标:")
                print(f"   平均耗时: {metrics['average_time_ms']:.2f}ms")
                print(f"   最小/最大: {metrics['min_time_ms']:.2f}ms / {metrics['max_time_ms']:.2f}ms")
                print(f"   返回行数: {metrics['row_count']}")
                print(f"   性能等级: {metrics['performance_level']}")

            # 显示索引建议
            if result["index_suggestions"]:
                print(f"\n💡 索引建议 ({len(result['index_suggestions'])}条):")
                for j, suggestion in enumerate(result['index_suggestions'][:3], 1):  # 只显示前3条
                    print(f"   {j}. {suggestion['reason']}")
                    if 'suggestion' in suggestion:
                        print(f"      建议: {suggestion['suggestion'][:60]}...")

            # 显示警告
            if result["warnings"]:
                print(f"\n⚠️ 性能警告:")
                for warning in result["warnings"]:
                    print(f"   {warning}")

        # 测试：获取表索引
        print(f"\n【测试 4】查询表索引")
        print("-" * 60)

        indexes = analyzer.get_table_indexes("orders")
        if indexes:
            print(f"orders表的索引 ({len(indexes)}个):")
            for idx in indexes:
                print(f"  - {idx['name']}: {', '.join(idx['columns'])}")
                if idx['unique']:
                    print(f"    (唯一索引)")
        else:
            print("orders表暂无索引")

        print("\n" + "=" * 60)
        print("✅ 测试完成！")
        print("=" * 60)

    except FileNotFoundError as e:
        print(f"❌ 错误: {e}")
        print("提示: 请确保数据库文件路径正确")
    except Exception as e:
        print(f"❌ 意外错误: {e}")