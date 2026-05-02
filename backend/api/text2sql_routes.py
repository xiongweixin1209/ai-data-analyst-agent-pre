"""
Text-to-SQL API Routes
包含生成、执行（带查询缓存）、优化、性能分析、批量生成的完整功能。
"""

import json
import re
import math
from fastapi import APIRouter, HTTPException
from typing import List, Optional

try:
    from ..services.text2sql_service import Text2SQLService
    from ..services.sql_executor import get_executor
    from ..services.datasource_manager import get_datasource_manager
    from ..services.sql_optimizer import get_optimizer
    from ..services.query_performance_analyzer import get_analyzer
    from ..services.query_cache_service import get_cache_service
    from .models import (
        Text2SQLRequest, Text2SQLResponse,
        BatchText2SQLRequest, BatchText2SQLResponse,
        ExampleStats, ExecuteSQLRequest, ExecuteSQLResponse,
        OptimizeSQLRequest, OptimizeSQLResponse,
        AnalyzeQueryRequest, AnalyzeQueryResponse
    )
except ImportError:
    from services.text2sql_service import Text2SQLService
    from services.sql_executor import get_executor
    from services.datasource_manager import get_datasource_manager
    from services.sql_optimizer import get_optimizer
    from services.query_performance_analyzer import get_analyzer
    from services.query_cache_service import get_cache_service
    from api.models import (
        Text2SQLRequest, Text2SQLResponse,
        BatchText2SQLRequest, BatchText2SQLResponse,
        ExampleStats, ExecuteSQLRequest, ExecuteSQLResponse,
        OptimizeSQLRequest, OptimizeSQLResponse,
        AnalyzeQueryRequest, AnalyzeQueryResponse
    )

router = APIRouter(prefix="/api/text2sql", tags=["Text-to-SQL"])

text2sql_service = Text2SQLService()
datasource_manager = get_datasource_manager()
sql_optimizer = get_optimizer()
cache_service = get_cache_service()


def convert_schema_to_dict(schema_list):
    """将 Pydantic 模型列表转换为字典列表（Pydantic v2 兼容）"""
    if not schema_list:
        return None
    return [
        {
            "table_name": table.table_name,
            "columns": [{"name": col.name, "type": col.type} for col in table.columns]
        }
        for table in schema_list
    ]


# ------------------------------------------------------------------ #
# 生成 SQL
# ------------------------------------------------------------------ #

@router.post("/generate", response_model=Text2SQLResponse)
async def generate_sql(request: Text2SQLRequest):
    try:
        schema_dicts = convert_schema_to_dict(request.table_schema)
        result = text2sql_service.generate_sql(
            query=request.query,
            schema=schema_dicts,
            force_strategy=request.force_strategy,
            datasource_id=str(request.datasource_id) if request.datasource_id else None
        )
        return Text2SQLResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL 生成失败: {str(e)}")


# ------------------------------------------------------------------ #
# 执行 SQL（含查询缓存）
# ------------------------------------------------------------------ #

@router.post("/execute", response_model=ExecuteSQLResponse)
async def execute_sql(request: ExecuteSQLRequest):
    try:
        datasource_id_str = str(request.datasource_id) if request.datasource_id else None

        # Step 1: 确定 SQL 来源
        if request.sql:
            sql = request.sql
            generation_result = {
                "success": True, "sql": sql, "strategy": "provided",
                "examples_used": 0,
                "stats": {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0, "duration_ms": 0}
            }
        else:
            if not request.query:
                raise HTTPException(status_code=400, detail="必须提供 query 或 sql 参数")

            schema_dicts = convert_schema_to_dict(request.table_schema)

            # Step 1a: 查询缓存
            cached = cache_service.get(request.query, datasource_id_str)
            if cached:
                sql = cached["sql"]
                generation_result = {
                    "success": True, "sql": sql,
                    "strategy": cached.get("strategy", "cached"),
                    "examples_used": 0,
                    "stats": {"prompt_tokens": 0, "completion_tokens": 0,
                              "total_tokens": 0, "duration_ms": 0},
                    "from_cache": True
                }
            else:
                # Step 1b: 调用 LLM 生成
                generation_result = text2sql_service.generate_sql(
                    query=request.query,
                    schema=schema_dicts,
                    force_strategy=request.force_strategy,
                    datasource_id=datasource_id_str
                )
                if not generation_result["success"]:
                    return ExecuteSQLResponse(
                        success=False,
                        sql=generation_result.get("sql", ""),
                        data=[], columns=[], row_count=0, execution_time=0,
                        error=generation_result.get("error", "SQL 生成失败"),
                        generation_stats=generation_result.get("stats", {}),
                        strategy=generation_result.get("strategy", "unknown")
                    )
                # 写入缓存
                cache_service.set(
                    request.query, datasource_id_str,
                    generation_result["sql"], generation_result.get("strategy")
                )

            sql = generation_result["sql"]

        # Step 2: 获取执行器
        if request.datasource_id:
            executor = datasource_manager.get_executor(datasource_id_str)
            if not executor:
                raise HTTPException(status_code=404,
                                    detail=f"数据源不存在: {request.datasource_id}")
        else:
            db_path = request.db_path or "D:/IndividualProject/text-to-sql/data/demo_ecommerce.db"
            executor = get_executor(db_path)

        # Step 3: 执行
        execution_result = executor.execute(sql, timeout=request.timeout)

        # Step 4: 优化建议
        optimization = None
        if request.include_optimization:
            schema_dicts = convert_schema_to_dict(request.table_schema)
            optimization = sql_optimizer.analyze(sql, schema_dicts)

        return ExecuteSQLResponse(
            success=execution_result["success"],
            sql=sql,
            data=execution_result["data"],
            columns=execution_result["columns"],
            row_count=execution_result["row_count"],
            execution_time=execution_result["execution_time"],
            error=execution_result.get("error"),
            warnings=execution_result.get("warnings", []),
            generation_stats=generation_result.get("stats", {}),
            strategy=generation_result.get("strategy", "unknown"),
            examples_used=generation_result.get("examples_used", 0),
            optimization=optimization
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"数据库文件不存在: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行失败: {str(e)}")


# ------------------------------------------------------------------ #
# SQL 优化建议
# ------------------------------------------------------------------ #

@router.post("/optimize", response_model=OptimizeSQLResponse)
async def optimize_sql(request: OptimizeSQLRequest):
    try:
        schema_dicts = convert_schema_to_dict(request.table_schema)
        result = sql_optimizer.analyze(sql=request.sql, schema=schema_dicts)
        return OptimizeSQLResponse(
            sql=request.sql,
            optimizable=result["optimizable"],
            suggestions=result["suggestions"],
            severity=result["severity"],
            estimated_improvement=result["estimated_improvement"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"优化分析失败: {str(e)}")


# ------------------------------------------------------------------ #
# 性能分析
# ------------------------------------------------------------------ #

@router.post("/analyze", response_model=AnalyzeQueryResponse)
async def analyze_query(request: AnalyzeQueryRequest):
    try:
        if request.datasource_id:
            datasource_info = datasource_manager.get_datasource_info(str(request.datasource_id))
            if not datasource_info:
                raise HTTPException(status_code=404,
                                    detail=f"数据源不存在: {request.datasource_id}")
            db_path = datasource_info["db_path"]
        else:
            db_path = request.db_path or "D:/IndividualProject/text-to-sql/data/demo_ecommerce.db"

        analyzer = get_analyzer(db_path)
        result = analyzer.analyze(request.sql)
        return AnalyzeQueryResponse(
            sql=request.sql,
            explain_plan=result["explain_plan"],
            performance_metrics=result["performance_metrics"],
            index_suggestions=result["index_suggestions"],
            warnings=result["warnings"]
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"数据库文件不存在: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"性能分析失败: {str(e)}")


# ------------------------------------------------------------------ #
# 批量生成（并发）
# ------------------------------------------------------------------ #

@router.post("/batch", response_model=BatchText2SQLResponse)
async def batch_generate_sql(request: BatchText2SQLRequest):
    try:
        schema_dicts = convert_schema_to_dict(request.table_schema)
        datasource_id_str = str(request.datasource_id) if hasattr(request, 'datasource_id') and request.datasource_id else None

        raw_results = text2sql_service.batch_generate(
            queries=request.queries,
            schema=schema_dicts,
            datasource_id=datasource_id_str,
            max_workers=4
        )
        results = [Text2SQLResponse(**r) for r in raw_results]
        return BatchText2SQLResponse(results=results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量生成失败: {str(e)}")


# ------------------------------------------------------------------ #
# 查询缓存统计
# ------------------------------------------------------------------ #

@router.get("/cache/stats")
async def get_cache_stats(limit: int = 20):
    """获取查询缓存统计和热门查询 Top N"""
    return cache_service.get_stats(limit=limit)


@router.delete("/cache")
async def clear_cache(datasource_id: Optional[str] = None):
    """清空查询缓存（可按数据源过滤）"""
    count = cache_service.clear(datasource_id)
    return {"deleted": count, "message": f"已清除 {count} 条缓存记录"}


# ------------------------------------------------------------------ #
# 健康检查 & 其他
# ------------------------------------------------------------------ #

@router.get("/health")
async def health_check():
    try:
        stats = text2sql_service.retriever.get_statistics()
        datasources = datasource_manager.list_datasources()
        cache_stats = cache_service.get_stats(limit=1)
        return {
            "status": "正常",
            "llm_available": text2sql_service.llm is not None,
            "examples_loaded": stats.get("total_examples", 0),
            "datasources_count": len(datasources),
            "cache_total": cache_stats.get("total_cached", 0),
            "features": {
                "text2sql": True, "execution": True,
                "optimization": True, "performance_analysis": True,
                "query_cache": True, "field_comments": True,
                "naive_bayes_classifier": True
            }
        }
    except Exception as e:
        return {"status": "异常", "message": str(e)}


@router.get("/examples/stats", response_model=ExampleStats)
async def get_example_stats():
    try:
        stats = text2sql_service.retriever.get_statistics()
        return ExampleStats(
            total_examples=stats.get("total_examples", 0),
            categories=stats.get("by_category", {}),
            difficulties=stats.get("by_difficulty", {})
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.get("/datasources")
async def list_datasources():
    try:
        datasources = datasource_manager.list_datasources()
        return {"success": True, "datasources": datasources, "count": len(datasources)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据源列表失败: {str(e)}")


@router.get("/datasources/{datasource_id}/schema")
async def get_datasource_schema(datasource_id: str):
    try:
        schema = datasource_manager.get_schema(datasource_id)
        if not schema["success"]:
            raise HTTPException(status_code=404, detail=schema["error"])
        return schema
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取 Schema 失败: {str(e)}")


@router.post("/plan")
async def plan_analysis(request: dict):
    """
    阶段二：分析需求拆解
    将业务问题拆解为 2-4 个具体的数据查询步骤，帮助分析员系统地展开分析。
    """
    business_question = request.get("business_question", "").strip()
    datasource_id = request.get("datasource_id")

    if not business_question:
        return {"success": False, "error": "请输入业务问题"}

    # 获取数据表上下文
    schema_context = ""
    if datasource_id:
        schema = datasource_manager.get_schema(str(datasource_id))
        if schema.get("success"):
            table_names = [t["table_name"] for t in schema.get("tables", [])]
            schema_context = f"\n可用数据表：{', '.join(table_names)}"

    prompt = f"""你是一位资深数据分析师。用户提出了一个业务分析问题，请将其拆解为2-4个具体的数据查询步骤，每步都能独立执行。
{schema_context}

业务问题：{business_question}

请严格按如下JSON格式输出，不要输出其他任何内容：
{{
  "analysis_goal": "用一句话描述本次分析的核心目标",
  "steps": [
    {{
      "step": 1,
      "description": "这一步要了解什么",
      "query": "对应的自然语言查询（可直接用于SQL生成）",
      "why": "为什么需要这一步"
    }}
  ]
}}"""

    result = text2sql_service.llm.generate(prompt=prompt, temperature=0.2, max_tokens=1000)
    if not result.get("success"):
        return {"success": False, "error": result.get("error", "分析规划失败")}

    try:
        raw = result.get("sql") or result.get("raw_response") or ""
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            plan = json.loads(json_match.group())
            return {"success": True, **plan}
    except Exception:
        pass

    return {"success": False, "error": "规划结果解析失败，请重试"}


def _detect_chart_type(intent: str, columns: list, data: list) -> str:
    """根据查询意图和数据结构规则推断最合适的图表类型"""
    if len(columns) < 2 or not data:
        return "bar"

    col0_vals = [str(row.get(columns[0], "")) for row in data[:5]]

    # 时间序列 → 折线图
    if any(re.search(r'\d{4}[-/年]\d{1,2}', v) for v in col0_vals):
        return "line"

    # 占比/分布关键词 → 饼图
    pie_kws = ["占比", "百分比", "比例", "分布", "构成", "份额", "percent"]
    if any(kw in intent.lower() for kw in pie_kws):
        return "pie"

    # 第一列也是数值 → 散点图
    try:
        if all(not math.isnan(float(row.get(columns[0], "x"))) for row in data[:5]):
            return "scatter"
    except (ValueError, TypeError):
        pass

    return "bar"


@router.post("/recommend-chart")
async def recommend_chart(request: dict):
    """根据查询意图和数据结构推断推荐图表类型（规则驱动，无 LLM 开销）"""
    intent = request.get("query_intent", "")
    columns = request.get("columns", [])
    sample_data = request.get("sample_data", [])

    chart_type = _detect_chart_type(intent, columns, sample_data)
    return {
        "success": True,
        "chart_type": chart_type,
        "available_types": ["bar", "line", "pie", "area", "scatter"]
    }


@router.post("/interpret")
async def interpret_results(request: dict):
    """对查询结果进行 AI 业务解读"""
    try:
        user_query = request.get("user_query", "")
        columns = request.get("columns", [])
        data = request.get("data", [])

        if not user_query or not columns or not data:
            return {"success": False, "interpretation": "", "error": "参数不完整"}

        return text2sql_service.interpret_results(
            user_query=user_query, columns=columns, data=data
        )
    except Exception as e:
        return {"success": False, "interpretation": "", "error": str(e)}
