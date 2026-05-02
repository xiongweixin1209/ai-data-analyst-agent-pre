#!/usr/bin/env python3
"""
Text-to-SQL Evaluator  —  eval/evaluator.py

用法:
    python eval/evaluator.py                          # 运行全部三种模式
    python eval/evaluator.py --mode default           # 仅运行默认模式
    python eval/evaluator.py --mode zero_shot_only
    python eval/evaluator.py --mode few_shot_top5
    python eval/evaluator.py --limit 10              # 只跑前10条用例（快速验证）

输出:
    eval/report.md  —  Markdown 格式评估报告

注意: 需要 Ollama 在本地运行且已加载 qwen2.5-coder:7b。
      rule 策略用例不调用 LLM，其余用例依赖 Ollama。

测试集说明:
    test_cases.json 共 80 条用例（设计指标为 70，实际按八类分布合计 80）
    单表查询(10)、多表联结(15)、聚合统计(15)、时序查询(10)、
    窗口函数(10)、复杂嵌套(10)、DWS表查询(5)、边界异常(5)
"""

import sys
import json
import time
import sqlite3
import argparse
import traceback
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime

# ── 路径配置 ──────────────────────────────────────────────────────────────────
EVAL_DIR = Path(__file__).parent
PROJECT_ROOT = EVAL_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
NORTHWIND_DB = PROJECT_ROOT / "data" / "northwind.db"
TEST_CASES_PATH = EVAL_DIR / "test_cases.json"
REPORT_PATH = EVAL_DIR / "report.md"

sys.path.insert(0, str(BACKEND_DIR))

try:
    import sqlparse
    HAS_SQLPARSE = True
except ImportError:
    HAS_SQLPARSE = False

# ── Schema 加载 ───────────────────────────────────────────────────────────────

def load_northwind_schema() -> List[Dict]:
    """直接从 northwind.db 读取表结构，返回 text2sql_service 期望的格式。"""
    conn = sqlite3.connect(str(NORTHWIND_DB))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    schema = []
    for table in tables:
        cursor.execute(f'PRAGMA table_info("{table}")')
        columns = [{"name": row[1], "type": row[2] or "TEXT"} for row in cursor.fetchall()]
        if columns:
            schema.append({"table_name": table, "columns": columns})
    conn.close()
    return schema

# ── SQL 验证与执行 ─────────────────────────────────────────────────────────────

def check_syntax(sql: str) -> bool:
    """检查 SQL 是否为合法的 SELECT 语句（语法层面）。"""
    if not sql or not sql.strip():
        return False
    sql = sql.strip().rstrip(";")
    if HAS_SQLPARSE:
        try:
            statements = sqlparse.parse(sql)
            if not statements:
                return False
            stmt_type = statements[0].get_type()
            return stmt_type == "SELECT"
        except Exception:
            return False
    # fallback: keyword check
    return sql.upper().lstrip().startswith("SELECT") or sql.upper().lstrip().startswith("WITH")


def execute_sql(sql: str, timeout_s: float = 10.0) -> Tuple[bool, str]:
    """在 northwind.db 上执行 SQL，返回 (成功, 错误信息)。
    只取前 20 行结果避免超时。不修改数据库（只接受 SELECT / WITH）。
    """
    if not sql or not sql.strip():
        return False, "Empty SQL"
    normalized = sql.strip().upper().lstrip()
    if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
        return False, "Non-SELECT statement blocked"
    try:
        conn = sqlite3.connect(str(NORTHWIND_DB), timeout=timeout_s)
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.cursor()
        cursor.execute(sql)
        cursor.fetchmany(20)
        conn.close()
        return True, ""
    except sqlite3.Error as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)

# ── 单条用例评估 ──────────────────────────────────────────────────────────────

def evaluate_case(
    case: Dict,
    service,
    mode: str,
    schema: List[Dict],
) -> Dict:
    """对单条测试用例调用 service，返回评估结果字典。"""
    query = case["query"]
    expected_strategy = case["expected_strategy"]

    # 根据模式确定 force_strategy 和 top_k patch
    force_strategy: Optional[str] = None
    original_retrieve = None

    if mode == "zero_shot_only":
        force_strategy = "zero_shot"
    elif mode == "few_shot_top5":
        force_strategy = "few_shot"
        original_retrieve = service.retriever.retrieve

        def _make_patched(orig):
            def _patched(query, top_k=5, **kwargs):  # noqa: E731
                return orig(query, top_k=5, **kwargs)
            return _patched

        service.retriever.retrieve = _make_patched(original_retrieve)

    t0 = time.time()
    try:
        result = service.generate_sql(
            query=query,
            schema=schema,
            force_strategy=force_strategy,
        )
    except Exception as exc:
        result = {
            "sql": "",
            "success": False,
            "error": str(exc),
            "strategy": "error",
        }
    elapsed_ms = round((time.time() - t0) * 1000, 1)

    # 还原 retriever patch
    if original_retrieve is not None:
        service.retriever.retrieve = original_retrieve

    generated_sql = result.get("sql", "").strip()
    actual_strategy = result.get("strategy", "unknown")
    llm_success = bool(result.get("success", False))

    # 指标
    syntax_ok = check_syntax(generated_sql) if llm_success and generated_sql else False
    if syntax_ok:
        exec_ok, exec_error = execute_sql(generated_sql)
    else:
        exec_ok, exec_error = False, ("LLM call failed" if not llm_success else "Syntax invalid")

    strategy_match = actual_strategy == expected_strategy

    return {
        "id": case["id"],
        "query": query,
        "category": case["intent_category"],
        "difficulty": case["difficulty"],
        "expected_strategy": expected_strategy,
        "actual_strategy": actual_strategy,
        "generated_sql": generated_sql,
        "llm_success": llm_success,
        "syntax_ok": syntax_ok,
        "exec_ok": exec_ok,
        "exec_error": exec_error,
        "strategy_match": strategy_match,
        "elapsed_ms": elapsed_ms,
    }

# ── 指标汇总 ─────────────────────────────────────────────────────────────────

def compute_metrics(results: List[Dict]) -> Dict:
    n = len(results)
    if n == 0:
        return {}
    return {
        "total": n,
        "llm_success_rate":       sum(r["llm_success"] for r in results) / n,
        "syntax_correct_rate":    sum(r["syntax_ok"]   for r in results) / n,
        "execution_success_rate": sum(r["exec_ok"]     for r in results) / n,
        "strategy_accuracy":      sum(r["strategy_match"] for r in results) / n,
        "avg_elapsed_ms":         sum(r["elapsed_ms"]  for r in results) / n,
    }


def category_breakdown(results: List[Dict]) -> Dict[str, Dict]:
    cats: Dict[str, Dict] = {}
    for r in results:
        c = r["category"]
        if c not in cats:
            cats[c] = {"total": 0, "syntax_ok": 0, "exec_ok": 0}
        cats[c]["total"] += 1
        if r["syntax_ok"]:
            cats[c]["syntax_ok"] += 1
        if r["exec_ok"]:
            cats[c]["exec_ok"] += 1
    return cats


def difficulty_breakdown(results: List[Dict]) -> Dict[str, Dict]:
    diffs: Dict[str, Dict] = {}
    for r in results:
        d = r["difficulty"]
        if d not in diffs:
            diffs[d] = {"total": 0, "exec_ok": 0}
        diffs[d]["total"] += 1
        if r["exec_ok"]:
            diffs[d]["exec_ok"] += 1
    return diffs

# ── 报告生成 ─────────────────────────────────────────────────────────────────

_CAT_LABELS = {
    "single_table":   "单表查询",
    "multi_join":     "多表联结",
    "aggregation":    "聚合统计",
    "time_series":    "时序查询",
    "window_function":"窗口函数",
    "complex_nested": "复杂嵌套",
    "dws_query":      "DWS表查询",
    "edge_case":      "边界异常",
}
_MODES = ["default", "zero_shot_only", "few_shot_top5"]
_MODE_LABELS = {
    "default":        "default（三层策略）",
    "zero_shot_only": "zero_shot_only",
    "few_shot_top5":  "few_shot_top5",
}


def generate_report(mode_results: Dict[str, Dict], output_path: Path) -> None:
    lines: List[str] = []

    def h(text: str) -> None:
        lines.append(text)

    h("# Text-to-SQL 评估报告")
    h("")
    h(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    first_mode = next(iter(mode_results.values()))
    h(f"> 测试用例数：{first_mode['metrics']['total']}  ")
    h(f"> 数据库：Northwind (`data/northwind.db`)  ")
    h(f"> 模型：qwen2.5-coder:7b (Ollama local)  ")
    h("")
    h("---")
    h("")

    # ── 汇总对比 ──
    h("## 一、汇总指标对比")
    h("")
    present_modes = [m for m in _MODES if m in mode_results]
    header = "| 指标 | " + " | ".join(_MODE_LABELS[m] for m in present_modes) + " |"
    sep    = "|---|" + "---|" * len(present_modes)
    h(header)
    h(sep)

    metric_rows = [
        ("llm_success_rate",       "LLM 调用成功率"),
        ("syntax_correct_rate",    "SQL 语法正确率"),
        ("execution_success_rate", "执行成功率 (EX)"),
        ("strategy_accuracy",      "策略分类准确率"),
    ]
    for key, label in metric_rows:
        cells = []
        for m in present_modes:
            val = mode_results[m]["metrics"].get(key, 0)
            cells.append(f"{val * 100:.1f}%")
        h(f"| {label} | " + " | ".join(cells) + " |")

    timing_cells = []
    for m in present_modes:
        v = mode_results[m]["metrics"].get("avg_elapsed_ms", 0)
        timing_cells.append(f"{v:.0f} ms")
    h(f"| 平均耗时 | " + " | ".join(timing_cells) + " |")

    h("")
    h("> **策略分类准确率** 在 zero_shot_only / few_shot_top5 模式下意义有限（策略被强制指定），仅供参考。")
    h("")
    h("---")
    h("")

    # ── 各类别执行成功率（default 模式）──
    if "default" in mode_results:
        h("## 二、各类别执行成功率（default 模式）")
        h("")
        h("| 类别 | 用例数 | 语法正确 | 执行成功 | EX 成功率 |")
        h("|---|---|---|---|---|")
        cat_data = category_breakdown(mode_results["default"]["results"])
        for cat in ["single_table","multi_join","aggregation","time_series",
                    "window_function","complex_nested","dws_query","edge_case"]:
            if cat in cat_data:
                d = cat_data[cat]
                rate = d["exec_ok"] / d["total"] * 100 if d["total"] else 0
                label = _CAT_LABELS.get(cat, cat)
                h(f"| {label} | {d['total']} | {d['syntax_ok']} | {d['exec_ok']} | {rate:.1f}% |")
        h("")
        h("---")
        h("")

    # ── 按难度分布（default 模式）──
    if "default" in mode_results:
        h("## 三、按难度的执行成功率（default 模式）")
        h("")
        h("| 难度 | 用例数 | 执行成功 | 成功率 |")
        h("|---|---|---|---|")
        diff_data = difficulty_breakdown(mode_results["default"]["results"])
        for d in ["easy", "medium", "hard", "expert"]:
            if d in diff_data:
                data = diff_data[d]
                rate = data["exec_ok"] / data["total"] * 100
                h(f"| {d} | {data['total']} | {data['exec_ok']} | {rate:.1f}% |")
        h("")
        h("---")
        h("")

    # ── 执行失败用例（default 模式）──
    if "default" in mode_results:
        h("## 四、执行失败用例（default 模式）")
        h("")
        failed = [r for r in mode_results["default"]["results"] if not r["exec_ok"]]
        if failed:
            h("| ID | 查询 | 类别 | 策略 | 错误信息 |")
            h("|---|---|---|---|---|")
            for r in failed[:30]:
                err  = (r.get("exec_error") or "")[:60].replace("|", "\\|")
                q    = r["query"][:28].replace("|", "\\|")
                cat  = _CAT_LABELS.get(r["category"], r["category"])
                h(f"| {r['id']} | {q} | {cat} | {r['actual_strategy']} | {err} |")
        else:
            h("全部用例执行成功。")
        h("")
        h("---")
        h("")

    # ── 策略分类错误用例（default 模式）──
    if "default" in mode_results:
        h("## 五、策略分类错误用例（default 模式）")
        h("")
        mismatches = [r for r in mode_results["default"]["results"] if not r["strategy_match"]]
        if mismatches:
            h("| ID | 查询 | 期望策略 | 实际策略 | 类别 |")
            h("|---|---|---|---|---|")
            for r in mismatches[:20]:
                q   = r["query"][:28].replace("|", "\\|")
                cat = _CAT_LABELS.get(r["category"], r["category"])
                h(f"| {r['id']} | {q} | {r['expected_strategy']} | {r['actual_strategy']} | {cat} |")
        else:
            h("策略分类全部正确。")
        h("")
        h("---")
        h("")

    # ── 模式对比：EX 成功率折线（文字形式）──
    if len(present_modes) > 1:
        h("## 六、模式对比 — 各类别 EX 成功率")
        h("")
        h("| 类别 | " + " | ".join(_MODE_LABELS[m] for m in present_modes) + " |")
        h("|---|" + "---|" * len(present_modes))
        for cat in ["single_table","multi_join","aggregation","time_series",
                    "window_function","complex_nested","dws_query","edge_case"]:
            cells = []
            for m in present_modes:
                cd = category_breakdown(mode_results[m]["results"])
                d = cd.get(cat, {"total": 0, "exec_ok": 0})
                rate = d["exec_ok"] / d["total"] * 100 if d["total"] else 0
                cells.append(f"{rate:.1f}%")
            label = _CAT_LABELS.get(cat, cat)
            h(f"| {label} | " + " | ".join(cells) + " |")
        h("")
        h("---")
        h("")

    h("*报告由 `eval/evaluator.py` 自动生成*")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅  报告已写入 {output_path}")

# ── 主流程 ─────────────────────────────────────────────────────────────────────

def run_mode(mode: str, test_cases: List[Dict], service, schema: List[Dict]) -> Dict:
    print(f"\n{'='*60}")
    print(f"  模式: {mode}  ({len(test_cases)} 条用例)")
    print(f"{'='*60}")

    results = []
    for case in test_cases:
        cid = case["id"]
        q_short = case["query"][:28]
        try:
            r = evaluate_case(case, service, mode, schema)
        except Exception as exc:
            traceback.print_exc()
            r = {
                "id": cid, "query": case["query"],
                "category": case["intent_category"],
                "difficulty": case["difficulty"],
                "expected_strategy": case["expected_strategy"],
                "actual_strategy": "error",
                "generated_sql": "",
                "llm_success": False, "syntax_ok": False,
                "exec_ok": False, "exec_error": str(exc),
                "strategy_match": False, "elapsed_ms": 0,
            }
        results.append(r)

        status_parts = [
            f"strat={r['actual_strategy']:<10}",
            f"llm={'✓' if r['llm_success'] else '✗'}",
            f"syn={'✓' if r['syntax_ok'] else '✗'}",
            f"ex={'✓' if r['exec_ok'] else '✗'}",
            f"{r['elapsed_ms']:.0f}ms",
        ]
        print(f"  [{cid:02d}] {q_short:<30} | {' | '.join(status_parts)}")

    metrics = compute_metrics(results)
    print(f"\n  ── {mode} 汇总 ──")
    print(f"  LLM成功率:  {metrics['llm_success_rate']*100:.1f}%")
    print(f"  语法正确率: {metrics['syntax_correct_rate']*100:.1f}%")
    print(f"  EX成功率:   {metrics['execution_success_rate']*100:.1f}%")
    print(f"  策略准确率: {metrics['strategy_accuracy']*100:.1f}%")
    print(f"  平均耗时:   {metrics['avg_elapsed_ms']:.0f}ms")

    return {"results": results, "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description="Text-to-SQL 评估脚本")
    parser.add_argument(
        "--mode",
        choices=["all", "default", "zero_shot_only", "few_shot_top5"],
        default="all",
        help="运行哪些模式的对比实验（默认: all）",
    )
    parser.add_argument(
        "--cases", type=Path, default=TEST_CASES_PATH,
        help="测试用例 JSON 路径",
    )
    parser.add_argument(
        "--output", type=Path, default=REPORT_PATH,
        help="报告输出路径",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="只运行前 N 条用例（0=全部，用于快速冒烟测试）",
    )
    args = parser.parse_args()

    # 加载测试用例
    print(f"📂  加载测试用例: {args.cases}")
    with open(args.cases, encoding="utf-8") as f:
        test_cases: List[Dict] = json.load(f)
    if args.limit > 0:
        test_cases = test_cases[: args.limit]
    print(f"    共 {len(test_cases)} 条用例")

    # 加载 Northwind schema
    print(f"📊  加载 Northwind schema: {NORTHWIND_DB}")
    schema = load_northwind_schema()
    print(f"    共 {len(schema)} 张表")

    # 初始化 service（会触发分类器训练，可能输出日志）
    print("🤖  初始化 Text2SQLService ...")
    from services.text2sql_service import get_text2sql_service
    service = get_text2sql_service()
    print("    初始化完成")

    # 决定运行哪些模式
    modes_to_run = _MODES if args.mode == "all" else [args.mode]

    mode_results: Dict[str, Dict] = {}
    for mode in modes_to_run:
        mode_results[mode] = run_mode(mode, test_cases, service, schema)

    # 生成报告
    generate_report(mode_results, args.output)


if __name__ == "__main__":
    main()
