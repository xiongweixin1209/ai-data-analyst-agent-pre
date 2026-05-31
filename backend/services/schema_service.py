"""
Schema读取服务
负责从数据库中读取表结构信息
"""

import sqlite3
from typing import List, Dict, Optional
from sqlalchemy import create_engine, inspect, text
from pathlib import Path

from models.datasource import DataSource
from config import settings


class SchemaService:
    """数据库Schema读取服务"""

    def __init__(self, datasource: DataSource):
        """
        初始化Schema服务

        Args:
            datasource: 数据源对象
        """
        self.datasource = datasource
        self.engine = self._create_engine()
        # 列存在性缓存(防止重复 PRAGMA 查询,避免每张表都重复探测)
        self._column_exists_cache: dict[str, bool] = {}

    def _column_exists(self, table_or_view: str, column: str) -> bool:
        """检查指定表/视图是否存在指定列。结果按 (table, column) 缓存,启动期一次性 probe。

        用于 graceful 处理"可选元数据"场景:Northwind 等数据库有 table_metadata
        表但缺 domain/layer 列;v_table_relationships 视图缺 related_table 列。
        没有这个 helper 的话,每张表的每次查询都会失败 + 打印一行错误,
        启动期可能产生几十行无效日志。
        """
        cache_key = f"{table_or_view}.{column}"
        if cache_key in self._column_exists_cache:
            return self._column_exists_cache[cache_key]

        exists = False
        try:
            with self.engine.connect() as conn:
                if self.datasource.type == "sqlite":
                    cols = conn.execute(text(f'PRAGMA table_info("{table_or_view}")')).fetchall()
                    col_names = {row[1] for row in cols}
                    exists = column in col_names
                # MySQL / PostgreSQL 没实现 — 真要用再补,目前 TTS 路径全是 SQLite
        except Exception:
            exists = False

        self._column_exists_cache[cache_key] = exists
        return exists

    def _create_engine(self):
        """根据数据源类型创建SQLAlchemy引擎"""

        if self.datasource.type == "sqlite":
            # SQLite数据库
            if not self.datasource.file_path:
                raise ValueError("SQLite数据源必须提供file_path")

            db_path = Path(self.datasource.file_path)
            if not db_path.exists():
                raise FileNotFoundError(f"数据库文件不存在: {self.datasource.file_path}")

            return create_engine(f"sqlite:///{self.datasource.file_path}")

        elif self.datasource.type == "mysql":
            # MySQL数据库
            connection_string = (
                f"mysql+pymysql://{self.datasource.username}:{self.datasource.password}"
                f"@{self.datasource.host}:{self.datasource.port}/{self.datasource.database}"
            )
            return create_engine(connection_string)

        elif self.datasource.type == "postgresql":
            # PostgreSQL数据库
            connection_string = (
                f"postgresql://{self.datasource.username}:{self.datasource.password}"
                f"@{self.datasource.host}:{self.datasource.port}/{self.datasource.database}"
            )
            return create_engine(connection_string)

        else:
            raise ValueError(f"不支持的数据库类型: {self.datasource.type}")

    def get_tables(self) -> List[str]:
        """
        获取所有表名

        Returns:
            表名列表
        """
        inspector = inspect(self.engine)
        return inspector.get_table_names()

    def get_columns(self, table_name: str) -> List[Dict[str, str]]:
        """
        获取指定表的所有字段信息

        Args:
            table_name: 表名

        Returns:
            字段信息列表，每个字段包含name和type
        """
        inspector = inspect(self.engine)
        columns = inspector.get_columns(table_name)

        return [
            {
                "name": col["name"],
                "type": str(col["type"]),
                "nullable": col.get("nullable", True),
                "default": str(col.get("default")) if col.get("default") else None
            }
            for col in columns
        ]

    def get_full_schema(self) -> Dict[str, List[Dict[str, str]]]:
        """
        获取完整的数据库Schema

        Returns:
            {
                "table1": [{"name": "id", "type": "INTEGER"}, ...],
                "table2": [...],
                ...
            }
        """
        tables = self.get_tables()
        schema = {}

        for table in tables:
            schema[table] = self.get_columns(table)

        return schema

    def get_sample_data(self, table_name: str, limit: int = 3) -> List[Dict]:
        """
        获取表的示例数据

        Args:
            table_name: 表名
            limit: 返回的记录数

        Returns:
            示例数据列表
        """
        with self.engine.connect() as connection:
            query = text(f"SELECT * FROM {table_name} LIMIT {limit}")
            result = connection.execute(query)
            columns = result.keys()

            return [
                dict(zip(columns, row))
                for row in result.fetchall()
            ]

    def get_statistics(self) -> Dict:
        """
        获取数据库统计信息

        Returns:
            {
                "total_tables": 表数量,
                "total_columns": 总字段数,
                "table_details": [...],
                "query_mode": "auto/smart/manual"
            }
        """
        schema = self.get_full_schema()

        total_tables = len(schema)
        total_columns = sum(len(cols) for cols in schema.values())

        # 获取每个表的记录数
        table_details = []
        for table_name, columns in schema.items():
            with self.engine.connect() as connection:
                count_query = text(f"SELECT COUNT(*) as count FROM {table_name}")
                result = connection.execute(count_query).fetchone()
                row_count = result[0] if result else 0

            table_details.append({
                "table_name": table_name,
                "column_count": len(columns),
                "row_count": row_count,
                "columns": columns
            })

        # 自动判断查询模式
        query_mode = self._determine_query_mode(total_tables, total_columns)

        return {
            "total_tables": total_tables,
            "total_columns": total_columns,
            "table_details": table_details,
            "query_mode": query_mode
        }

    def _determine_query_mode(self, total_tables: int, total_columns: int) -> str:
        """
        自动判断应该使用的查询模式

        Args:
            total_tables: 表数量
            total_columns: 总字段数

        Returns:
            "auto": 自动全量模式（小型数据库）
            "smart": 智能选择模式（中型数据库）
            "manual": 手动指定模式（大型数据库）
        """
        if total_tables <= settings.AUTO_MODE_MAX_TABLES and \
                total_columns <= settings.AUTO_MODE_MAX_COLUMNS:
            return "auto"
        elif total_tables <= settings.AUTO_MODE_MAX_TABLES * 2:
            return "smart"
        else:
            return "manual"

    def close(self):
        """关闭数据库连接"""
        if self.engine:
            self.engine.dispose()

    # ========== 以下是新增的方法（在类内部） ==========

    def detect_layer(self, table_name: str) -> str:
        """
        检测表的层级（DWD/DWS）

        Args:
            table_name: 表名

        Returns:
            "DWD" - 明细层
            "DWS" - 汇总层
            "UNKNOWN" - 未知
        """
        # 方法1:从 table_metadata.layer 读(若表/列都存在)
        tables = self.get_tables()
        if "table_metadata" in tables and self._column_exists("table_metadata", "layer"):
            try:
                with self.engine.connect() as connection:
                    query = text(
                        "SELECT layer FROM table_metadata WHERE table_name = :table_name"
                    )
                    result = connection.execute(query, {"table_name": table_name}).fetchone()
                    if result:
                        return result[0]
            except Exception as e:
                print(f"从table_metadata读取层级失败: {e}")

        # 方法2：基于命名规则判断
        table_lower = table_name.lower()
        if table_lower.startswith("dws_"):
            return "DWS"
        elif table_lower.startswith("dwd_"):
            return "DWD"

        # 方法3：基于表名关键词判断（如果没有前缀）
        dws_keywords = ["summary", "daily", "agg", "aggregation", "stats", "statistics"]
        if any(keyword in table_lower for keyword in dws_keywords):
            return "DWS"

        # 默认认为是明细层
        return "DWD"

    def analyze_domain(self, table_name: str) -> str:
        """
        分析表所属的业务域

        Args:
            table_name: 表名

        Returns:
            业务域名称，如 "订单域"、"客户域" 等
        """
        # 方法1:从 table_metadata.domain 读(若表/列都存在)
        tables = self.get_tables()
        if "table_metadata" in tables and self._column_exists("table_metadata", "domain"):
            try:
                with self.engine.connect() as connection:
                    query = text(
                        "SELECT domain FROM table_metadata WHERE table_name = :table_name"
                    )
                    result = connection.execute(query, {"table_name": table_name}).fetchone()
                    if result and result[0]:
                        return result[0]
            except Exception as e:
                print(f"从table_metadata读取业务域失败: {e}")

        # 方法2：基于表名关键词判断
        table_lower = table_name.lower()

        # 订单相关
        if any(keyword in table_lower for keyword in ["order", "invoice", "订单"]):
            return "订单域"

        # 客户相关
        if any(keyword in table_lower for keyword in ["customer", "client", "user", "客户", "用户"]):
            return "客户域"

        # 产品相关
        if any(keyword in table_lower for keyword in ["product", "goods", "item", "category", "产品", "商品"]):
            return "产品域"

        # 员工相关
        if any(keyword in table_lower for keyword in ["employee", "staff", "territory", "员工"]):
            return "员工域"

        # 供应商相关
        if any(keyword in table_lower for keyword in ["supplier", "vendor", "供应商"]):
            return "供应商域"

        # 物流相关
        if any(keyword in table_lower for keyword in ["ship", "delivery", "freight", "物流", "配送"]):
            return "物流域"

        return "其他"

    def get_performance_level(self, row_count: int, layer: str) -> str:
        """
        评估表的查询性能等级

        Args:
            row_count: 记录数
            layer: 表层级（DWD/DWS）

        Returns:
            "fast" - 快速（<1秒）
            "medium" - 中等（1-5秒）
            "slow" - 较慢（>5秒）
        """
        # DWS层通常很快（因为已聚合）
        if layer == "DWS":
            return "fast"

        # DWD层根据记录数判断
        if row_count < 1000:
            return "fast"
        elif row_count < 50000:
            return "medium"
        else:
            return "slow"

    def get_table_relationships(self, table_name: str) -> List[str]:
        """
        获取表的关联关系

        Args:
            table_name: 表名

        Returns:
            关联表列表
        """
        # 方法1：从v_table_relationships视图读取
        tables = self.get_tables()
        views = []
        try:
            with self.engine.connect() as connection:
                # 获取所有视图
                if self.datasource.type == "sqlite":
                    query = text("SELECT name FROM sqlite_master WHERE type='view'")
                    result = connection.execute(query)
                    views = [row[0] for row in result.fetchall()]
        except Exception as e:
            print(f"获取视图列表失败: {e}")

        if "v_table_relationships" in views and self._column_exists("v_table_relationships", "related_table"):
            try:
                with self.engine.connect() as connection:
                    query = text("""
                        SELECT related_table
                        FROM v_table_relationships
                        WHERE table_name = :table_name
                    """)
                    result = connection.execute(query, {"table_name": table_name}).fetchall()
                    return [row[0] for row in result]
            except Exception as e:
                print(f"从v_table_relationships读取关系失败: {e}")

        # 方法2：基于外键关系分析（SQLite的外键信息）
        related_tables = []
        try:
            inspector = inspect(self.engine)
            foreign_keys = inspector.get_foreign_keys(table_name)
            for fk in foreign_keys:
                related_tables.append(fk['referred_table'])
        except Exception as e:
            print(f"分析外键关系失败: {e}")

        return related_tables

    def get_use_cases(self, table_name: str, layer: str, domain: str) -> List[str]:
        """
        生成表的适用场景建议

        Args:
            table_name: 表名
            layer: 表层级
            domain: 业务域

        Returns:
            适用场景列表
        """
        use_cases = []

        if layer == "DWS":
            # 汇总层适合的场景
            use_cases.append("趋势分析")
            use_cases.append("统计报表")

            if "daily" in table_name.lower() or "日" in table_name:
                use_cases.append("日报生成")
            if "summary" in table_name.lower() or "汇总" in table_name:
                use_cases.append("指标监控")
        else:
            # 明细层适合的场景
            use_cases.append("明细查询")
            use_cases.append("灵活筛选")

            if domain == "订单域":
                use_cases.append("订单追踪")
                use_cases.append("交易分析")
            elif domain == "客户域":
                use_cases.append("客户画像")
                use_cases.append("用户行为分析")
            elif domain == "产品域":
                use_cases.append("商品管理")
                use_cases.append("库存分析")

        return use_cases

    def get_enhanced_statistics(self) -> Dict:
        """
        获取增强的数据库统计信息（包含DWD/DWS分层）

        Returns:
            {
                "datasource_id": 数据源ID,
                "datasource_name": 数据源名称,
                "total_tables": 总表数,
                "total_columns": 总字段数,
                "dwd_table_count": DWD层表数,
                "dws_table_count": DWS层表数,
                "query_mode": 查询模式,
                "has_layer_info": 是否有分层信息,
                "domains": 业务域列表,
                "table_details": 表详情列表（增强版）
            }
        """
        schema = self.get_full_schema()
        total_tables = len(schema)
        total_columns = sum(len(cols) for cols in schema.values())

        # 统计DWD和DWS表数量
        dwd_count = 0
        dws_count = 0
        domains = set()

        # 获取每个表的详细信息
        table_details = []
        for table_name, columns in schema.items():
            # 跳过元数据表和视图
            if table_name in ["table_metadata", "v_table_relationships"]:
                continue

            # 获取记录数
            with self.engine.connect() as connection:
                count_query = text(f'SELECT COUNT(*) as count FROM "{table_name}"')
                result = connection.execute(count_query).fetchone()
                row_count = result[0] if result else 0

            # 检测层级
            layer = self.detect_layer(table_name)
            if layer == "DWD":
                dwd_count += 1
            elif layer == "DWS":
                dws_count += 1

            # 分析业务域
            domain = self.analyze_domain(table_name)
            domains.add(domain)

            # 性能等级
            performance_level = self.get_performance_level(row_count, layer)

            # 关联表
            related_tables = self.get_table_relationships(table_name)

            # 适用场景
            use_cases = self.get_use_cases(table_name, layer, domain)

            table_details.append({
                "table_name": table_name,
                "column_count": len(columns),
                "row_count": row_count,
                "columns": columns,
                "layer": layer,
                "domain": domain,
                "performance_level": performance_level,
                "related_tables": related_tables,
                "use_cases": use_cases
            })

        # 判断查询模式
        query_mode = self._determine_query_mode(total_tables, total_columns)

        # 判断是否有分层信息
        has_layer_info = dws_count > 0

        return {
            "datasource_id": self.datasource.id,
            "datasource_name": self.datasource.name,
            "total_tables": total_tables - 1 if "table_metadata" in schema else total_tables,  # 排除元数据表
            "total_columns": total_columns,
            "dwd_table_count": dwd_count,
            "dws_table_count": dws_count,
            "query_mode": query_mode,
            "has_layer_info": has_layer_info,
            "domains": sorted(list(domains)),
            "table_details": table_details
        }

    def recommend_tables(self, user_query: str) -> Dict:
        """
        基于用户查询推荐合适的表（使用LLM）

        Args:
            user_query: 用户的查询需求描述

        Returns:
            {
                "success": True/False,
                "recommendations": [
                    {
                        "table_name": "表名",
                        "confidence": "high/medium/low",
                        "reason": "推荐理由",
                        "match_keywords": ["关键词1", "关键词2"]
                    }
                ],
                "alternatives": ["备选表1", "备选表2"],
                "error": "错误信息（如果有）"
            }
        """
        try:
            # 获取数据库元信息
            stats = self.get_enhanced_statistics()
            table_details = stats.get("table_details", [])

            if not table_details:
                return {
                    "success": False,
                    "error": "数据库中没有可用的表",
                    "recommendations": [],
                    "alternatives": []
                }

            # 构造表信息摘要（简化版，减少token）
            tables_summary = []
            for table in table_details:
                summary = {
                    "name": table["table_name"],
                    "layer": table["layer"],
                    "domain": table["domain"],
                    "row_count": table["row_count"],
                    "performance": table["performance_level"],
                    "use_cases": table["use_cases"],
                    "key_columns": [col["name"] for col in table["columns"][:5]]  # 只取前5个字段
                }
                tables_summary.append(summary)

            # 构造Prompt
            prompt = f"""你是一个数据库表推荐专家。根据用户的查询需求，从候选表中推荐最合适的2-3张表。

用户需求：{user_query}

可用的表：
{self._format_tables_for_prompt(tables_summary)}

分析要点：
1. 如果需求包含"统计/汇总/趋势/每天/每月"等关键词，优先推荐DWS汇总层表（性能快）
2. 如果需求包含"详细/明细/具体/订单号"等关键词，推荐DWD明细层表（灵活）
3. 根据业务域匹配表（订单域、客户域、产品域等）
4. 考虑性能等级（fast > medium > slow）

请以JSON格式返回推荐，不要包含任何其他内容，不要使用markdown代码块：
{{
  "recommendations": [
    {{
      "table_name": "表名",
      "confidence": "high",
      "reason": "推荐理由（一句话，不超过30字）",
      "match_keywords": ["匹配的关键词"]
    }}
  ],
  "alternatives": ["备选表1", "备选表2"]
}}"""

            # 调用Ollama
            import requests
            ollama_url = "http://localhost:11434/api/generate"

            response = requests.post(
                ollama_url,
                json={
                    "model": "qwen2.5-coder:7b",
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.3,  # 降低温度，提高确定性
                    "format": "json"  # 要求JSON格式输出
                },
                timeout=30
            )

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": "调用LLM服务失败",
                    "recommendations": [],
                    "alternatives": []
                }

            llm_response = response.json()
            llm_output = llm_response.get("response", "")

            # 解析LLM返回的JSON
            import json
            import re

            # 清理可能的markdown代码块标记
            llm_output = re.sub(r'```json\s*', '', llm_output)
            llm_output = re.sub(r'```\s*', '', llm_output)
            llm_output = llm_output.strip()

            try:
                result = json.loads(llm_output)

                # 验证推荐的表是否真实存在
                valid_tables = {t["table_name"] for t in table_details}
                filtered_recommendations = []

                for rec in result.get("recommendations", []):
                    if rec.get("table_name") in valid_tables:
                        filtered_recommendations.append(rec)

                # 过滤备选表
                filtered_alternatives = [
                    t for t in result.get("alternatives", [])
                    if t in valid_tables
                ]

                return {
                    "success": True,
                    "recommendations": filtered_recommendations[:3],  # 最多3个推荐
                    "alternatives": filtered_alternatives[:3],  # 最多3个备选
                    "error": None
                }

            except json.JSONDecodeError as e:
                print(f"JSON解析失败: {e}")
                print(f"LLM输出: {llm_output}")
                return {
                    "success": False,
                    "error": "LLM返回格式错误",
                    "recommendations": [],
                    "alternatives": []
                }

        except Exception as e:
            print(f"推荐表失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "recommendations": [],
                "alternatives": []
            }

    def _format_tables_for_prompt(self, tables_summary: List[Dict]) -> str:
        """格式化表信息用于Prompt"""
        formatted = []
        for i, table in enumerate(tables_summary, 1):
            formatted.append(
                f"{i}. {table['name']} ({table['layer']}, {table['domain']}, {table['row_count']}条记录)\n"
                f"   - 性能: {table['performance']}\n"
                f"   - 适用: {', '.join(table['use_cases'])}\n"
                f"   - 关键字段: {', '.join(table['key_columns'])}"
            )
        return "\n\n".join(formatted)

# ========== 辅助函数（类外部） ==========

def get_schema_service(datasource: DataSource) -> SchemaService:
    """
    工厂函数：创建SchemaService实例

    Args:
        datasource: 数据源对象

    Returns:
        SchemaService实例
    """
    return SchemaService(datasource)