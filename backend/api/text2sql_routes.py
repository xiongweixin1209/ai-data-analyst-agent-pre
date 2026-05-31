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
    from ..config import settings
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
    from config import settings
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

def _resolve_schema(
    table_schema_param,
    datasource_id_str: Optional[str],
) -> list:
    """统一的 schema 解析:
    1) 优先用请求里显式传的 table_schema(转 dict)
    2) 空时若有 datasource_id,自动从 datasource_manager 加载
    3) 都没有就返回 [](下游会报 Schema 不能为空)
    """
    schema_dicts = convert_schema_to_dict(table_schema_param)
    if schema_dicts:
        return schema_dicts
    if datasource_id_str:
        ds_schema = datasource_manager.get_schema(datasource_id_str)
        if ds_schema.get("success"):
            return ds_schema.get("tables", []) or []
    return []


@router.post("/generate", response_model=Text2SQLResponse)
async def generate_sql(request: Text2SQLRequest):
    try:
        ds_id_str = str(request.datasource_id) if request.datasource_id else None
        schema_dicts = _resolve_schema(request.table_schema, ds_id_str)
        result = text2sql_service.generate_sql(
            query=request.query,
            schema=schema_dicts,
            force_strategy=request.force_strategy,
            datasource_id=ds_id_str,
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

            # schema 兜底解析:显式 schema 优先,否则从 datasource_id 自动加载
            schema_dicts = _resolve_schema(request.table_schema, datasource_id_str)

            # Step 1a: 查询缓存（按 query + datasource + schema指纹 + force_strategy）
            cached = cache_service.get(
                request.query, datasource_id_str,
                schema=schema_dicts, force_strategy=request.force_strategy,
            )
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
                    generation_result["sql"], generation_result.get("strategy"),
                    schema=schema_dicts, force_strategy=request.force_strategy,
                )

            sql = generation_result["sql"]

        # Step 2: 获取执行器
        if request.datasource_id:
            executor = datasource_manager.get_executor(datasource_id_str)
            if not executor:
                raise HTTPException(status_code=404,
                                    detail=f"数据源不存在: {request.datasource_id}")
        else:
            db_path = request.db_path or settings.DEMO_DB_PATH
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
            db_path = request.db_path or settings.DEMO_DB_PATH

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
            categories=stats.get("categories", {}),
            difficulties=stats.get("difficulties", {})
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


# ============================================================
# Manual-step Agent 工具白名单
# ============================================================
# LLM 在 /plan 拆解时为每步指定一个工具,前端按工具调用对应端点。
# 用户手动点击每步执行(不自动连贯),状态完全可见、可控。
# 工具集精简到 4 个,覆盖业务分析的核心动作:
#   理解 schema → 写 SQL → 执行拿数据 → 业务解读
ALLOWED_AGENT_TOOLS = {
    "lookup_schema",     # 查 schema/表字段详情(用 datasource_id + table_name)
    "generate_sql",      # 自然语言 → SQL(只生成不执行)
    "execute_sql",       # 自然语言 → SQL → 执行(返回数据)
    "interpret_results", # 数据 → 业务解读文字(基于上一步结果)
}
DEFAULT_AGENT_TOOL = "execute_sql"  # LLM 没标 tool 时的兜底


@router.post("/plan")
async def plan_analysis(request: dict):
    """
    Manual-step Agent · 分析需求拆解
    ----------------------------------------------------------------
    把业务问题拆解为 2-4 个步骤,每步标注 tool(工具),前端按工具
    调对应端点。设计上**不自动连贯执行** —— 用户手动点击每步执行,
    每步结果可见可控。

    这种"规划+人控"模式适合数据分析场景:分析师要在每一步审视
    中间结果决定下一步,而不是一头扎进去等终局。
    """
    business_question = request.get("business_question", "").strip()
    datasource_id = request.get("datasource_id")

    if not business_question:
        return {"success": False, "error": "请输入业务问题"}

    # 获取数据表上下文 —— 拿表名 + 字段名(给 lookup_schema 步骤参考)
    schema_context = ""
    if datasource_id:
        schema = datasource_manager.get_schema(str(datasource_id))
        if schema.get("success"):
            tables = schema.get("tables", [])
            table_names = [t["table_name"] for t in tables]
            schema_context = f"\n可用数据表:{', '.join(table_names)}"

    prompt = f"""你是一位资深数据分析师,正在帮用户用 Manual-step Agent 拆解业务问题。
{schema_context}

业务问题:{business_question}

把这个业务问题拆解为 2-4 个步骤,每步标注要调用的"工具"。可用的工具有 4 个:

  1. lookup_schema     —— 查看某张表的字段详情(只读元信息,不查数据)
                          适合:开始分析前先弄清楚表结构
                          input 字段填:表名(从上面可用数据表列表里挑)

  2. generate_sql      —— 把自然语言查询变成 SQL,但不执行
                          适合:用户想先看 SQL 再决定要不要跑
                          input 字段填:自然语言查询

  3. execute_sql       —— 生成 SQL 并执行,返回数据
                          适合:大多数"我想看数据"的步骤
                          input 字段填:自然语言查询

  4. interpret_results —— 把数据变成业务洞察文字
                          适合:数据出来后想要一段业务总结
                          input 字段填:自然语言查询(同上一步即可)

请按如下 JSON 格式严格输出(只输出 JSON,不要解释、不要 markdown 包装):

{{
  "analysis_goal": "用一句话概括本次分析的核心目标",
  "steps": [
    {{
      "step": 1,
      "tool": "工具名(必须从上面 4 个里选一个)",
      "description": "这一步要做什么(用户视角的简短描述,15 字内)",
      "input": "工具的输入,见下面详细说明",
      "why": "为什么需要这一步(给用户解释 1 句话)"
    }}
  ]
}}

【input 字段填什么 —— 关键说明,必须严格遵守】
- 若 tool="lookup_schema"     :input 填**表名**(单个英文表名,如 "Orders" / "Customers")
- 若 tool="generate_sql"      :input 填**中文自然语言查询**(如"查询销售额最高的产品")
- 若 tool="execute_sql"       :input 填**中文自然语言查询**(同上,**绝对不要写 SQL!**)
- 若 tool="interpret_results" :input 填**中文自然语言查询**(同上)

⚠️ 重点警告:input 字段**永远不要直接写 SQL 语句**!
   即使 tool="execute_sql",你也只填中文问题描述,SQL 由系统自动生成。
   反例(错误):"SELECT * FROM Orders LIMIT 10"
   正例(正确):"查询前 10 条订单"

【其他约束】
- steps 数量 2-4 条,**不要超过 4 步**
- 第一步通常是 lookup_schema(理解表结构)或 execute_sql(直接拿数据)
- 中间步骤多用 execute_sql 拿数据
- 最后一步用 interpret_results 给业务结论(可选)
- tool 字段必须是 4 个工具名之一,**不能编造**
"""

    result = text2sql_service.llm.generate(prompt=prompt, temperature=0.2, max_tokens=1200)
    if not result.get("success"):
        return {"success": False, "error": result.get("error", "分析规划失败")}

    raw = result.get("sql") or result.get("raw_response") or ""
    try:
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return {"success": False, "error": "规划结果解析失败,LLM 输出未含合法 JSON"}
        plan = json.loads(json_match.group())
    except Exception as e:
        return {"success": False, "error": f"JSON 解析异常:{e}"}

    # 校验 + 规整每个步骤
    valid_steps = []
    for i, step in enumerate(plan.get("steps", []), 1):
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool", "")).strip().lower()
        if tool not in ALLOWED_AGENT_TOOLS:
            tool = DEFAULT_AGENT_TOOL  # 不合法的工具名 → 降级为 execute_sql
        valid_steps.append({
            "step":         step.get("step", i),
            "tool":         tool,
            "description":  str(step.get("description", "")).strip(),
            "input":        str(step.get("input") or step.get("query") or "").strip(),
            "why":          str(step.get("why", "")).strip(),
        })

    if not valid_steps:
        return {"success": False, "error": "规划失败:LLM 没产出合法步骤"}

    return {
        "success": True,
        "analysis_goal": str(plan.get("analysis_goal", "")).strip(),
        "steps": valid_steps,
    }


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

    # 散点图需要前两列都是数值
    if _column_is_numeric(data, columns[0]) and _column_is_numeric(data, columns[1]):
        return "scatter"

    return "bar"


def _column_is_numeric(data: list, col: str, sample: int = 5) -> bool:
    """判断列在前 N 行内是否全为可解析的数值"""
    rows = data[:sample]
    if not rows:
        return False
    for row in rows:
        val = row.get(col)
        if val is None or val == "":
            return False
        try:
            f = float(val)
        except (ValueError, TypeError):
            return False
        if math.isnan(f):
            return False
    return True


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
