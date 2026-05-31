/**
 * QueryPlanner - Manual-step Agent
 * ============================================================
 * 用户描述业务问题 → AI 拆解为 2-4 个步骤,每步带工具标签 → 用户手动点击执行
 *
 * 设计理念:
 *   - **Plan-then-Execute Agent 范式**:LLM 只规划,用户决定执行节奏
 *   - **每步独立工具调用**:lookup_schema / generate_sql / execute_sql / interpret_results
 *   - **状态全可见**:中间结果实时展示在步骤卡片下方,不黑盒
 *   - **不做自动连贯**:每步要用户点,有效控制错误传播,适合数据分析场景
 */

import React, { useState } from 'react';
import {
  Target, ChevronDown, ChevronUp, Loader2,
  Database, Code2, Play, Lightbulb, CheckCircle2, XCircle,
} from 'lucide-react';
import { text2sqlAPI, datasourceAPI } from '../services/api';
import { useApp } from '../context/AppContext';

// ============================================================
// 工具元信息:Tailwind JIT 要求完整类名字符串,这里做静态映射
// ============================================================
const TOOL_META = {
  lookup_schema: {
    label: '查 Schema',
    icon: Database,
    accent: 'blue',
    badge: 'bg-blue-100 text-blue-700 border-blue-200',
    btn: 'bg-blue-500 hover:bg-blue-600',
    desc: '查看某张表的字段详情',
  },
  generate_sql: {
    label: '生成 SQL',
    icon: Code2,
    accent: 'purple',
    badge: 'bg-purple-100 text-purple-700 border-purple-200',
    btn: 'bg-purple-500 hover:bg-purple-600',
    desc: '把自然语言转成 SQL,但不执行',
  },
  execute_sql: {
    label: '执行查询',
    icon: Play,
    accent: 'green',
    badge: 'bg-green-100 text-green-700 border-green-200',
    btn: 'bg-green-500 hover:bg-green-600',
    desc: '生成 SQL 并执行,返回数据',
  },
  interpret_results: {
    label: '业务解读',
    icon: Lightbulb,
    accent: 'orange',
    badge: 'bg-orange-100 text-orange-700 border-orange-200',
    btn: 'bg-orange-500 hover:bg-orange-600',
    desc: '把数据变成业务洞察文字',
  },
};

const QueryPlanner = ({ onSelectQuery, datasourceId }) => {
  const { datasourceSchema } = useApp();

  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [plan, setPlan] = useState(null);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState(null);

  // 每步独立状态:{ [stepNumber]: { loading, result, error } }
  const [stepStates, setStepStates] = useState({});

  // ============================================================
  // 规划:调 /plan,LLM 拆解业务问题
  // ============================================================
  const handlePlan = async () => {
    if (!question.trim()) return;
    setPlanning(true);
    setPlanError(null);
    setPlan(null);
    setStepStates({});
    try {
      const result = await text2sqlAPI.planAnalysis(question.trim(), datasourceId);
      if (result.success) {
        setPlan(result);
      } else {
        setPlanError(result.error || '规划失败,请重试');
      }
    } catch (e) {
      setPlanError(e.message);
    } finally {
      setPlanning(false);
    }
  };

  // ============================================================
  // 执行某一步:根据工具名调对应端点
  // ============================================================
  const handleExecuteStep = async (step) => {
    const stepNum = step.step;
    setStepStates(prev => ({
      ...prev,
      [stepNum]: { loading: true, result: null, error: null },
    }));

    try {
      let result;
      switch (step.tool) {
        case 'lookup_schema':
          result = await runLookupSchema(step.input);
          break;
        case 'generate_sql':
          result = await runGenerateSql(step.input);
          break;
        case 'execute_sql':
          result = await runExecuteSql(step.input);
          break;
        case 'interpret_results':
          result = await runInterpretResults(step.input);
          break;
        default:
          throw new Error(`未知工具:${step.tool}`);
      }
      setStepStates(prev => ({
        ...prev,
        [stepNum]: { loading: false, result, error: null },
      }));
    } catch (e) {
      setStepStates(prev => ({
        ...prev,
        [stepNum]: { loading: false, result: null, error: e.message },
      }));
    }
  };

  // ============================================================
  // 工具实现:每个工具一个独立函数,职责单一
  // ============================================================
  const runLookupSchema = async (tableName) => {
    if (!datasourceId) throw new Error('请先选择数据源');
    const fullSchema = await datasourceAPI.getEnhancedSchema(datasourceId);
    // /datasource/{id}/schema 实际返回字段叫 table_details,不是 tables
    // (这里兼容两种叫法以防后端变更)
    const tables = fullSchema?.table_details
                || fullSchema?.tables
                || [];
    // 模糊匹配表名(LLM 标的可能跟实际有大小写/空格差异)
    const norm = (s) => String(s || '').toLowerCase().replace(/[\s"]/g, '');
    const found = tables.find(t => norm(t.table_name) === norm(tableName))
                  || tables.find(t => norm(t.table_name).includes(norm(tableName)));
    if (!found) {
      throw new Error(`找不到表 "${tableName}",可用表:${tables.map(t => t.table_name).join(', ')}`);
    }
    return { type: 'schema', table: found };
  };

  const runGenerateSql = async (query) => {
    // datasourceSchema 来自 /datasource/{id}/schema(enhanced 端点),
    // 字段叫 table_details(不是 tables)。这里防御性兼容两种字段名。
    const schemaList = datasourceSchema?.table_details
                     || datasourceSchema?.tables
                     || [];
    // 同时把 datasourceId 传给后端 —— 万一前端 schemaList 是空,
    // 后端会用 datasource_id 兜底加载
    const resp = await text2sqlAPI.generate(query, schemaList, null, datasourceId);
    return {
      type: 'sql_only',
      sql: resp.sql,
      strategy: resp.strategy,
      success: resp.success,
      error: resp.error,
    };
  };

  const runExecuteSql = async (query) => {
    // datasourceSchema 来自 /datasource/{id}/schema(enhanced 端点),
    // 字段叫 table_details(不是 tables)。这里防御性兼容两种字段名。
    const schemaList = datasourceSchema?.table_details
                     || datasourceSchema?.tables
                     || [];
    const resp = await text2sqlAPI.execute({
      query,
      schema: schemaList,
      datasourceId,
      includeOptimization: false,
    });
    return {
      type: 'execution',
      sql: resp.sql,
      data: resp.data || [],
      columns: resp.columns || [],
      rowCount: resp.row_count,
      success: resp.success,
      error: resp.error,
      strategy: resp.strategy,
    };
  };

  const runInterpretResults = async (query) => {
    // interpret 需要先有数据。这里先执行 SQL,再调 /interpret
    // datasourceSchema 来自 /datasource/{id}/schema(enhanced 端点),
    // 字段叫 table_details(不是 tables)。这里防御性兼容两种字段名。
    const schemaList = datasourceSchema?.table_details
                     || datasourceSchema?.tables
                     || [];
    const execResp = await text2sqlAPI.execute({
      query,
      schema: schemaList,
      datasourceId,
      includeOptimization: false,
    });
    if (!execResp.success) {
      throw new Error(`SQL 执行失败:${execResp.error}`);
    }
    // 调 /interpret 端点(走 fetch,因为 api.js 里没封装这个端点)
    const interpResp = await fetch('http://localhost:8000/api/text2sql/interpret', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_query: query,
        columns: execResp.columns,
        data: execResp.data,
      }),
    }).then(r => r.json());
    return {
      type: 'interpretation',
      sql: execResp.sql,
      data: execResp.data,
      columns: execResp.columns,
      interpretation: interpResp.interpretation || '(未能生成解读)',
    };
  };

  // ============================================================
  // UI 渲染
  // ============================================================
  return (
    <div className="backdrop-blur-sm bg-white/80 rounded-2xl shadow-lg border border-gray-200/50 overflow-hidden mb-6">
      {/* 标题栏 */}
      <button
        className="w-full flex items-center justify-between p-5 hover:bg-gray-50/50 transition-colors"
        onClick={() => setOpen(prev => !prev)}
      >
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-gradient-to-br from-violet-500 to-purple-600 rounded-xl flex items-center justify-center shadow-md shadow-violet-500/30">
            <Target className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <p className="text-sm font-bold text-gray-800">AI 分析规划(Manual-step Agent)</p>
            <p className="text-xs text-gray-500">描述业务问题 → AI 拆解步骤 + 标注工具 → 你点哪步执行哪步</p>
          </div>
        </div>
        {open
          ? <ChevronUp className="w-5 h-5 text-gray-400" />
          : <ChevronDown className="w-5 h-5 text-gray-400" />
        }
      </button>

      {open && (
        <div className="px-5 pb-5 space-y-4 border-t border-gray-100">
          {/* 输入栏 */}
          <div className="flex gap-2 mt-4">
            <input
              type="text"
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !planning && handlePlan()}
              placeholder="例如:为什么上周销售额下降了?哪些用户流失了?"
              className="flex-1 px-4 py-2.5 border border-gray-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent bg-white"
            />
            <button
              onClick={handlePlan}
              disabled={planning || !question.trim()}
              className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-violet-500 to-purple-600 text-white rounded-xl text-sm font-semibold disabled:opacity-50 hover:opacity-90 transition-all shadow-md shadow-violet-500/30"
            >
              {planning
                ? <><Loader2 className="w-4 h-4 animate-spin" />规划中</>
                : <>开始规划</>
              }
            </button>
          </div>

          {planError && (
            <p className="text-sm text-red-600 bg-red-50 px-4 py-2 rounded-lg">{planError}</p>
          )}

          {plan && (
            <div className="space-y-3">
              {/* 分析目标 */}
              <div className="flex items-start gap-2 p-3 bg-violet-50 rounded-xl border border-violet-100">
                <span className="text-violet-600 text-sm">🎯</span>
                <p className="text-sm font-semibold text-violet-800">{plan.analysis_goal}</p>
              </div>

              {/* 步骤列表 */}
              <div className="space-y-3">
                {plan.steps?.map((step) => (
                  <StepCard
                    key={step.step}
                    step={step}
                    state={stepStates[step.step]}
                    onExecute={() => handleExecuteStep(step)}
                    onSelectQuery={onSelectQuery}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ============================================================
// StepCard:单步卡片(头部 + 工具按钮 + 结果区)
// ============================================================
const StepCard = ({ step, state, onExecute, onSelectQuery }) => {
  const meta = TOOL_META[step.tool] || TOOL_META.execute_sql;
  const ToolIcon = meta.icon;
  const loading = state?.loading;
  const result = state?.result;
  const error = state?.error;

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden hover:border-violet-200 hover:shadow-sm transition-all">
      {/* 头部 */}
      <div className="flex items-start gap-3 p-4">
        <span className="flex-shrink-0 w-6 h-6 bg-violet-500 text-white rounded-full flex items-center justify-center text-xs font-bold mt-0.5">
          {step.step}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <p className="text-sm font-semibold text-gray-800">{step.description}</p>
            {/* 工具标签 */}
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium border ${meta.badge}`}>
              <ToolIcon className="w-3 h-3" />
              {meta.label}
            </span>
          </div>
          <p className="text-xs text-gray-500 mb-2">{step.why}</p>
          <div className="px-3 py-1.5 bg-gray-50 rounded-lg border border-gray-100">
            <span className="text-xs text-gray-400 mr-2">输入:</span>
            <code className="text-xs text-gray-700">{step.input}</code>
          </div>
        </div>
        {/* 执行按钮 */}
        <button
          onClick={onExecute}
          disabled={loading}
          className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-white rounded-lg text-xs font-semibold transition-colors shadow-sm mt-0.5 disabled:opacity-50 ${meta.btn}`}
        >
          {loading
            ? <><Loader2 className="w-3 h-3 animate-spin" />运行中</>
            : <>执行 <ToolIcon className="w-3 h-3" /></>
          }
        </button>
      </div>

      {/* 结果区(loading / error / 各工具特定的结果展示) */}
      {(loading || result || error) && (
        <div className="border-t border-gray-100 bg-gray-50/40 px-4 py-3">
          {loading && (
            <p className="text-xs text-gray-500 flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" /> 工具 {meta.label} 执行中...
            </p>
          )}
          {error && (
            <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 rounded-lg p-2">
              <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}
          {result && <ResultRenderer result={result} onSelectQuery={onSelectQuery} stepInput={step.input} />}
        </div>
      )}
    </div>
  );
};

// ============================================================
// ResultRenderer:按工具类型渲染不同的结果展示
// ============================================================
const ResultRenderer = ({ result, onSelectQuery, stepInput }) => {
  // type 由各 run* 函数返回时标记
  if (result.type === 'schema') return <SchemaResultView table={result.table} />;
  if (result.type === 'sql_only') return <SqlOnlyView result={result} onSelectQuery={onSelectQuery} query={stepInput} />;
  if (result.type === 'execution') return <ExecutionView result={result} />;
  if (result.type === 'interpretation') return <InterpretationView result={result} />;
  return null;
};

const SchemaResultView = ({ table }) => (
  <div>
    <p className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-1">
      <CheckCircle2 className="w-3 h-3 text-green-500" />
      表 <code className="text-blue-600">{table.table_name}</code> · {table.columns?.length || 0} 个字段
    </p>
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-500 border-b border-gray-200">
            <th className="text-left py-1.5 px-2">字段名</th>
            <th className="text-left py-1.5 px-2">类型</th>
            <th className="text-left py-1.5 px-2">备注</th>
          </tr>
        </thead>
        <tbody>
          {(table.columns || []).slice(0, 12).map((col, i) => (
            <tr key={i} className="border-b border-gray-100">
              <td className="py-1.5 px-2 font-mono text-gray-800">{col.name}</td>
              <td className="py-1.5 px-2 text-gray-500">{col.type}</td>
              <td className="py-1.5 px-2 text-gray-400">
                {col.primary_key && <span className="mr-1 px-1 bg-yellow-100 text-yellow-700 rounded text-[10px]">PK</span>}
                {col.not_null && <span className="mr-1 px-1 bg-red-100 text-red-700 rounded text-[10px]">NOT NULL</span>}
              </td>
            </tr>
          ))}
          {table.columns?.length > 12 && (
            <tr><td colSpan={3} className="py-1.5 px-2 text-gray-400 text-center">... 还有 {table.columns.length - 12} 个字段</td></tr>
          )}
        </tbody>
      </table>
    </div>
  </div>
);

const SqlOnlyView = ({ result, onSelectQuery, query }) => (
  <div>
    <p className="text-xs font-semibold text-gray-700 mb-1.5 flex items-center gap-2">
      <CheckCircle2 className="w-3 h-3 text-green-500" />
      生成的 SQL <span className="text-gray-400">策略:{result.strategy}</span>
    </p>
    <pre className="text-xs bg-gray-900 text-green-300 rounded-lg p-3 overflow-x-auto font-mono">{result.sql}</pre>
    <button
      onClick={() => onSelectQuery?.(query)}
      className="mt-2 text-xs text-violet-600 hover:underline"
    >
      → 把这条查询填到主输入框
    </button>
  </div>
);

const ExecutionView = ({ result }) => (
  <div>
    <p className="text-xs font-semibold text-gray-700 mb-1.5 flex items-center gap-2">
      <CheckCircle2 className="w-3 h-3 text-green-500" />
      返回 {result.rowCount} 行 · 策略 {result.strategy}
    </p>
    <details className="mb-2">
      <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">展开 SQL</summary>
      <pre className="text-xs bg-gray-900 text-green-300 rounded-lg p-2 overflow-x-auto font-mono mt-1">{result.sql}</pre>
    </details>
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-500 border-b border-gray-200">
            {(result.columns || []).map(c => (
              <th key={c} className="text-left py-1.5 px-2">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(result.data || []).slice(0, 10).map((row, i) => (
            <tr key={i} className="border-b border-gray-100">
              {(result.columns || []).map(c => (
                <td key={c} className="py-1.5 px-2 text-gray-700">{String(row[c] ?? '')}</td>
              ))}
            </tr>
          ))}
          {result.data?.length > 10 && (
            <tr><td colSpan={result.columns?.length} className="py-1.5 px-2 text-gray-400 text-center">
              ... 还有 {result.data.length - 10} 行
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  </div>
);

const InterpretationView = ({ result }) => (
  <div>
    <p className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-2">
      <Lightbulb className="w-3 h-3 text-orange-500" />
      AI 业务解读
    </p>
    <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 text-sm text-gray-800 leading-relaxed">
      {result.interpretation}
    </div>
    <details className="mt-2">
      <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">展开底层数据({result.data?.length || 0} 行)</summary>
      <pre className="text-xs bg-gray-50 rounded p-2 mt-1 overflow-x-auto max-h-40">
{JSON.stringify(result.data?.slice(0, 5) || [], null, 2)}
      </pre>
    </details>
  </div>
);

export default QueryPlanner;
