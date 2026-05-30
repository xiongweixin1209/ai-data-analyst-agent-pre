"""
SQL Executor - SQL执行器
功能：安全执行SQL查询并返回格式化结果
"""

import sqlite3
import time
from typing import Dict, List, Any, Optional
from pathlib import Path

# 兼容两种导入方式
try:
    from .sql_validator import get_validator
except ImportError:
    from sql_validator import get_validator


class SQLExecutor:
    """SQL执行器"""

    def __init__(self, db_path: str):
        """
        初始化执行器

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.validator = get_validator()

        # 检查数据库文件是否存在
        if not Path(db_path).exists():
            raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    def execute(
            self,
            sql: str,
            params: Optional[tuple] = None,
            timeout: int = 30
    ) -> Dict:
        """
        执行SQL查询

        Args:
            sql: SQL语句
            params: 查询参数（可选）
            timeout: 超时时间（秒）

        Returns:
            Dict: {
                "success": bool,
                "data": List[Dict],  # 查询结果
                "columns": List[str],  # 字段名
                "row_count": int,  # 行数
                "execution_time": float,  # 执行时间（毫秒）
                "error": str  # 错误信息
            }
        """
        start_time = time.time()

        try:
            # 1. 验证SQL
            validation = self.validator.validate(sql)
            if not validation["valid"]:
                return {
                    "success": False,
                    "data": [],
                    "columns": [],
                    "row_count": 0,
                    "execution_time": 0,
                    "error": validation["error"],
                    "warnings": validation.get("warnings", [])
                }

            # 2. 执行查询
            conn = None
            try:
                # 连接数据库（只读模式）
                conn = sqlite3.connect(
                    f"file:{self.db_path}?mode=ro",
                    uri=True,
                    timeout=timeout
                )
                conn.row_factory = sqlite3.Row  # 使用Row对象，可以按列名访问
                cursor = conn.cursor()

                # 执行查询
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)

                # 获取结果
                rows = cursor.fetchall()

                # 格式化结果
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                data = [dict(row) for row in rows]
                row_count = len(rows)

                execution_time = (time.time() - start_time) * 1000  # 转换为毫秒

                # 计算数据统计信息（新增）
                statistics = self._calculate_statistics(data, columns)

                return {
                    "success": True,
                    "data": data,
                    "columns": columns,
                    "row_count": row_count,
                    "execution_time": round(execution_time, 2),
                    "statistics": statistics,  # 新增统计信息
                    "error": None,
                    "warnings": validation.get("warnings", [])
                }

            finally:
                if conn:
                    conn.close()

        except sqlite3.OperationalError as e:
            execution_time = (time.time() - start_time) * 1000
            error_msg = str(e)

            # 友好的错误信息
            if "no such table" in error_msg:
                error_msg = f"表不存在: {error_msg.split(':')[1].strip()}"
            elif "no such column" in error_msg:
                error_msg = f"字段不存在: {error_msg.split(':')[1].strip()}"
            elif "syntax error" in error_msg:
                error_msg = f"SQL语法错误: {error_msg}"

            return {
                "success": False,
                "data": [],
                "columns": [],
                "row_count": 0,
                "execution_time": round(execution_time, 2),
                "error": error_msg,
                "warnings": []
            }

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            return {
                "success": False,
                "data": [],
                "columns": [],
                "row_count": 0,
                "execution_time": round(execution_time, 2),
                "error": f"执行错误: {str(e)}",
                "warnings": []
            }

    def test_connection(self) -> Dict:
        """
        测试数据库连接

        Returns:
            Dict: {
                "success": bool,
                "message": str,
                "tables": List[str]
            }
        """
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            cursor = conn.cursor()

            # 获取所有表名
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
            )
            tables = [row[0] for row in cursor.fetchall()]

            conn.close()

            return {
                "success": True,
                "message": "连接成功",
                "tables": tables
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"连接失败: {str(e)}",
                "tables": []
            }

    def get_table_info(self, table_name: str) -> Dict:
        """
        获取表结构信息

        Args:
            table_name: 表名

        Returns:
            Dict: {
                "success": bool,
                "columns": List[Dict],
                "row_count": int,
                "error": str
            }
        """
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            cursor = conn.cursor()

            # 获取表结构
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = []
            for row in cursor.fetchall():
                columns.append({
                    "name": row[1],
                    "type": row[2],
                    "not_null": bool(row[3]),
                    "default": row[4],
                    "primary_key": bool(row[5])
                })

            # 获取行数
            cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
            row_count = cursor.fetchone()[0]

            conn.close()

            return {
                "success": True,
                "columns": columns,
                "row_count": row_count,
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "columns": [],
                "row_count": 0,
                "error": str(e)
            }

    def _calculate_statistics(self, data: List[Dict], columns: List[str]) -> Dict:
        """
        计算查询结果的统计信息

        Args:
            data: 查询结果数据
            columns: 列名列表

        Returns:
            Dict: {
                "column_count": int,
                "numeric_columns": Dict[str, Dict]
            }
        """
        if not data or not columns:
            return {
                "column_count": len(columns),
                "numeric_columns": {}
            }

        # 识别数值列并计算统计信息
        numeric_stats = {}

        for col in columns:
            # 收集该列的所有非空数值
            values = []
            for row in data:
                value = row.get(col)
                # 尝试转换为数值
                if value is not None:
                    try:
                        # 尝试转换为float
                        if isinstance(value, (int, float)):
                            values.append(float(value))
                        elif isinstance(value, str):
                            # 尝试将字符串转换为数值
                            values.append(float(value))
                    except (ValueError, TypeError):
                        # 不是数值，跳过
                        continue

            # 如果有有效的数值，计算统计信息
            if values:
                numeric_stats[col] = {
                    "sum": round(sum(values), 2),
                    "avg": round(sum(values) / len(values), 2),
                    "max": round(max(values), 2),
                    "min": round(min(values), 2),
                    "count": len(values)
                }

        return {
            "column_count": len(columns),
            "numeric_columns": numeric_stats
        }


def get_executor(db_path: str) -> SQLExecutor:
    """获取执行器实例"""
    return SQLExecutor(db_path)


# ============================================================
# 测试代码
# ============================================================
if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config import settings

    print("=" * 60)
    print("测试SQL执行器")
    print("=" * 60)

    # 使用 demo 数据库(路径从配置读,避免硬编码)
    db_path = settings.DEMO_DB_PATH

    try:
        executor = get_executor(db_path)

        # 测试1：连接测试
        print("\n【测试1：数据库连接】")
        print("-" * 60)
        conn_test = executor.test_connection()
        if conn_test["success"]:
            print(f"✅ {conn_test['message']}")
            print(f"📊 找到 {len(conn_test['tables'])} 个表:")
            for table in conn_test['tables']:
                print(f"   - {table}")
        else:
            print(f"❌ {conn_test['message']}")
            exit(1)

        # 测试2：简单查询
        print("\n【测试2：简单查询】")
        print("-" * 60)
        sql = "SELECT * FROM orders LIMIT 5;"
        result = executor.execute(sql)

        print(f"SQL: {sql}")
        print(f"成功: {result['success']}")
        print(f"行数: {result['row_count']}")
        print(f"字段: {', '.join(result['columns'])}")
        print(f"执行时间: {result['execution_time']}ms")
        if result['data']:
            print(f"第一行数据: {result['data'][0]}")

        # 测试3：聚合查询
        print("\n【测试3：聚合查询】")
        print("-" * 60)
        sql = "SELECT country, COUNT(*) as count FROM orders GROUP BY country LIMIT 5;"
        result = executor.execute(sql)

        print(f"SQL: {sql}")
        print(f"成功: {result['success']}")
        print(f"结果:")
        for row in result['data']:
            print(f"   {row['country']}: {row['count']}")

        # 测试4：WHERE条件
        print("\n【测试4：WHERE条件查询】")
        print("-" * 60)
        sql = "SELECT * FROM orders WHERE quantity > 50 LIMIT 3;"
        result = executor.execute(sql)

        print(f"SQL: {sql}")
        print(f"找到 {result['row_count']} 条记录")
        print(f"执行时间: {result['execution_time']}ms")

        # 测试5：复杂聚合
        print("\n【测试5：复杂聚合查询】")
        print("-" * 60)
        sql = """
            SELECT 
                stock_code,
                SUM(quantity * unit_price) as total_sales
            FROM orders
            GROUP BY stock_code
            ORDER BY total_sales DESC
            LIMIT 5;
        """
        result = executor.execute(sql)

        print(f"成功: {result['success']}")
        if result['success']:
            print(f"销售额Top 5商品:")
            for row in result['data']:
                print(f"   {row['stock_code']}: ${row['total_sales']:.2f}")

        # 测试6：错误SQL（应该被拦截）
        print("\n【测试6：危险SQL测试】")
        print("-" * 60)
        sql = "DROP TABLE orders;"
        result = executor.execute(sql)

        print(f"SQL: {sql}")
        print(f"成功: {result['success']}")
        if not result['success']:
            print(f"✅ 成功拦截: {result['error']}")
        else:
            print(f"❌ 未能拦截危险SQL！")

        # 测试7：表信息查询
        print("\n【测试7：表结构信息】")
        print("-" * 60)
        table_info = executor.get_table_info("orders")

        if table_info["success"]:
            print(f"✅ 表名: orders")
            print(f"📊 总行数: {table_info['row_count']}")
            print(f"🔧 字段信息:")
            for col in table_info['columns']:
                pk = " [PK]" if col['primary_key'] else ""
                nn = " [NOT NULL]" if col['not_null'] else ""
                print(f"   - {col['name']} ({col['type']}){pk}{nn}")

        print("\n" + "=" * 60)
        print("✅ 所有测试完成！")
        print("=" * 60)

    except FileNotFoundError as e:
        print(f"❌ 错误: {e}")
        print("提示: 请确保数据库文件路径正确")
    except Exception as e:
        print(f"❌ 意外错误: {e}")