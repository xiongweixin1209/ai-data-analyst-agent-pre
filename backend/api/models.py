"""
API Data Models (完整版)
包含所有接口的请求和响应模型
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any


# ============================================================
# 基础模型
# ============================================================

class TableColumn(BaseModel):
    """表字段信息"""
    name: str = Field(..., description="字段名")
    type: str = Field(..., description="字段类型")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "user_id",
            "type": "INTEGER"
        }
    })


class TableSchema(BaseModel):
    """表结构信息"""
    table_name: str = Field(..., description="表名")
    columns: List[TableColumn] = Field(..., description="字段列表")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "table_name": "users",
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "username", "type": "TEXT"}
            ]
        }
    })


class TokenStats(BaseModel):
    """Token使用统计"""
    prompt_tokens: int = Field(0, description="Prompt tokens")
    completion_tokens: int = Field(0, description="生成tokens")
    total_tokens: int = Field(0, description="总tokens")
    duration_ms: float = Field(0, description="生成耗时(毫秒)")


# ============================================================
# Text-to-SQL 生成
# ============================================================

class Text2SQLRequest(BaseModel):
    """Text-to-SQL生成请求"""
    query: str = Field(..., description="自然语言查询", min_length=1)
    table_schema: Optional[List[TableSchema]] = Field(
        None,
        alias="schema",
        description="数据库Schema(可选;如果提供 datasource_id,schema 可省略,后端会自动加载)"
    )
    datasource_id: Optional[str] = Field(
        None,
        description="数据源 ID(可选);若提供,可省略 schema(后端自动加载),同时启用字段注释注入"
    )
    force_strategy: Optional[str] = Field(
        None,
        description="强制使用的策略 (rule/few_shot/zero_shot)"
    )

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "query": "查询所有用户",
                "schema": [
                    {
                        "table_name": "users",
                        "columns": [
                            {"name": "id", "type": "INTEGER"},
                            {"name": "username", "type": "TEXT"}
                        ]
                    }
                ]
            }
        }
    )


class Text2SQLResponse(BaseModel):
    """Text-to-SQL生成响应"""
    success: bool = Field(..., description="是否成功")
    sql: str = Field(..., description="生成的SQL语句")
    error: Optional[str] = Field(None, description="错误信息")
    strategy: str = Field(..., description="使用的策略")
    examples_used: int = Field(0, description="使用的示例数量")
    stats: TokenStats = Field(..., description="Token使用统计")


# ============================================================
# SQL 执行
# ============================================================

class ExecuteSQLRequest(BaseModel):
    """执行SQL请求"""
    query: Optional[str] = Field(None, description="自然语言查询")
    sql: Optional[str] = Field(None, description="直接提供的SQL")
    table_schema: Optional[List[TableSchema]] = Field(
        None,
        alias="schema",
        description="数据库Schema（生成SQL时需要）"
    )
    datasource_id: Optional[str] = Field(None, description="数据源ID")
    db_path: Optional[str] = Field(None, description="数据库文件路径")
    force_strategy: Optional[str] = Field(None, description="强制策略")
    timeout: int = Field(30, description="超时时间（秒）", ge=1, le=300)
    include_optimization: bool = Field(False, description="是否包含优化建议")

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "query": "查询销售额最高的前10个商品",
                "schema": [
                    {
                        "table_name": "orders",
                        "columns": [
                            {"name": "stock_code", "type": "TEXT"},
                            {"name": "quantity", "type": "INTEGER"},
                            {"name": "unit_price", "type": "REAL"}
                        ]
                    }
                ],
                "include_optimization": True
            }
        }
    )


class ExecuteSQLResponse(BaseModel):
    """执行SQL响应"""
    success: bool = Field(..., description="是否成功")
    sql: str = Field(..., description="执行的SQL语句")
    data: List[Dict[str, Any]] = Field(..., description="查询结果数据")
    columns: List[str] = Field(..., description="字段名列表")
    row_count: int = Field(..., description="返回行数")
    execution_time: float = Field(..., description="执行时间（毫秒）")
    error: Optional[str] = Field(None, description="错误信息")
    warnings: List[str] = Field(default_factory=list, description="警告信息")
    generation_stats: Optional[TokenStats] = Field(None, description="SQL生成统计")
    strategy: str = Field(..., description="使用的生成策略")
    examples_used: int = Field(0, description="使用的示例数量")
    optimization: Optional[Dict] = Field(None, description="优化建议")


# ============================================================
# SQL 优化
# ============================================================

class OptimizeSQLRequest(BaseModel):
    """SQL优化请求"""
    sql: str = Field(..., description="待优化的SQL", min_length=1)
    table_schema: Optional[List[TableSchema]] = Field(
        None,
        alias="schema",
        description="数据库Schema（可选）"
    )

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "sql": "SELECT * FROM orders WHERE YEAR(order_date) = 2024;"
            }
        }
    )


class OptimizationSuggestion(BaseModel):
    """单个优化建议"""
    type: str = Field(..., description="建议类型")
    severity: str = Field(..., description="严重程度 (low/medium/high)")
    message: str = Field(..., description="建议描述")
    suggestion: str = Field(..., description="具体建议")
    reason: str = Field(..., description="原因说明")
    example: Optional[str] = Field(None, description="示例SQL")


class OptimizeSQLResponse(BaseModel):
    """SQL优化响应"""
    sql: str = Field(..., description="原始SQL")
    optimizable: bool = Field(..., description="是否可优化")
    suggestions: List[OptimizationSuggestion] = Field(..., description="优化建议列表")
    severity: str = Field(..., description="整体严重程度")
    estimated_improvement: str = Field(..., description="预期改善程度")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "sql": "SELECT * FROM orders;",
            "optimizable": True,
            "suggestions": [
                {
                    "type": "missing_limit",
                    "severity": "medium",
                    "message": "建议添加LIMIT",
                    "suggestion": "添加 LIMIT 100",
                    "reason": "避免返回过多数据",
                    "example": "SELECT * FROM orders LIMIT 100;"
                }
            ],
            "severity": "medium",
            "estimated_improvement": "中等改善（10-20%）"
        }
    })


# ============================================================
# 查询性能分析
# ============================================================

class AnalyzeQueryRequest(BaseModel):
    """查询性能分析请求"""
    sql: str = Field(..., description="待分析的SQL", min_length=1)
    datasource_id: Optional[str] = Field(None, description="数据源ID")
    db_path: Optional[str] = Field(None, description="数据库文件路径")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "sql": "SELECT * FROM orders WHERE quantity > 10 LIMIT 100;",
            "datasource_id": "demo"
        }
    })


class QueryPlan(BaseModel):
    """查询计划"""
    steps: List[Dict] = Field(..., description="执行步骤")
    has_table_scan: bool = Field(..., description="是否有全表扫描")
    uses_index: bool = Field(..., description="是否使用索引")
    complexity: str = Field(..., description="复杂度 (simple/medium/complex)")


class PerformanceMetrics(BaseModel):
    """性能指标"""
    average_time_ms: float = Field(..., description="平均执行时间（毫秒）")
    min_time_ms: float = Field(..., description="最小执行时间")
    max_time_ms: float = Field(..., description="最大执行时间")
    row_count: int = Field(..., description="返回行数")
    runs: int = Field(..., description="测试运行次数")
    performance_level: str = Field(..., description="性能等级")


class IndexSuggestion(BaseModel):
    """索引建议"""
    type: str = Field(..., description="建议类型")
    reason: str = Field(..., description="原因")
    suggestion: str = Field(..., description="具体建议")
    expected_improvement: str = Field(..., description="预期改善")
    field: Optional[str] = Field(None, description="相关字段")


class AnalyzeQueryResponse(BaseModel):
    """查询性能分析响应"""
    sql: str = Field(..., description="分析的SQL")
    explain_plan: Optional[QueryPlan] = Field(None, description="查询计划")
    performance_metrics: Optional[PerformanceMetrics] = Field(None, description="性能指标")
    index_suggestions: List[IndexSuggestion] = Field(default_factory=list, description="索引建议")
    warnings: List[str] = Field(default_factory=list, description="性能警告")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "sql": "SELECT * FROM orders WHERE quantity > 10;",
            "explain_plan": {
                "steps": [{"id": 0, "detail": "SCAN TABLE orders"}],
                "has_table_scan": True,
                "uses_index": False,
                "complexity": "simple"
            },
            "performance_metrics": {
                "average_time_ms": 45.23,
                "min_time_ms": 43.1,
                "max_time_ms": 48.7,
                "row_count": 150,
                "runs": 3,
                "performance_level": "good"
            },
            "index_suggestions": [],
            "warnings": ["⚠️ 查询使用了全表扫描"]
        }
    })


# ============================================================
# 批量处理
# ============================================================

class BatchText2SQLRequest(BaseModel):
    """批量Text-to-SQL请求"""
    queries: List[str] = Field(..., description="查询列表", min_length=1)
    table_schema: List[TableSchema] = Field(
        ...,
        alias="schema",
        description="数据库Schema"
    )
    force_strategy: Optional[str] = Field(None, description="强制策略")

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "queries": [
                    "查询所有用户",
                    "统计用户数量"
                ],
                "schema": [
                    {
                        "table_name": "users",
                        "columns": [
                            {"name": "id", "type": "INTEGER"}
                        ]
                    }
                ]
            }
        }
    )


class BatchText2SQLResponse(BaseModel):
    """批量Text-to-SQL响应"""
    results: List[Text2SQLResponse] = Field(..., description="批量结果")


# ============================================================
# 示例统计
# ============================================================

class ExampleStats(BaseModel):
    """示例库统计信息"""
    total_examples: int = Field(..., description="总示例数")
    categories: Dict[str, int] = Field(..., description="按类别统计")
    difficulties: Dict[str, int] = Field(..., description="按难度统计")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "total_examples": 74,
            "categories": {
                "simple_filter": 15,
                "aggregation": 15
            },
            "difficulties": {
                "easy": 30,
                "medium": 35
            }
        }
    })