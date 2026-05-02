/**
 * QueryPlanner - 分析需求拆解组件（阶段二）
 * 用户描述业务问题 → AI 拆解为 2-4 个具体查询步骤 → 点击步骤直接执行
 */

import React, { useState } from 'react';
import { Target, ChevronDown, ChevronUp, ArrowRight, Loader2 } from 'lucide-react';
import { text2sqlAPI } from '../services/api';

const QueryPlanner = ({ onSelectQuery, datasourceId }) => {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handlePlan = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setPlan(null);
    try {
      const result = await text2sqlAPI.planAnalysis(question.trim(), datasourceId);
      if (result.success) {
        setPlan(result);
      } else {
        setError(result.error || '规划失败，请重试');
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectQuery = (query) => {
    onSelectQuery(query);
  };

  return (
    <div className="backdrop-blur-sm bg-white/80 rounded-2xl shadow-lg border border-gray-200/50 overflow-hidden mb-6">
      {/* 标题栏（可折叠） */}
      <button
        className="w-full flex items-center justify-between p-5 hover:bg-gray-50/50 transition-colors"
        onClick={() => setOpen(prev => !prev)}
      >
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-gradient-to-br from-violet-500 to-purple-600 rounded-xl flex items-center justify-center shadow-md shadow-violet-500/30">
            <Target className="w-4 h-4 text-white" />
          </div>
          <div className="text-left">
            <p className="text-sm font-bold text-gray-800">分析规划</p>
            <p className="text-xs text-gray-500">描述业务问题，AI 自动拆解为可执行的查询步骤</p>
          </div>
        </div>
        {open
          ? <ChevronUp className="w-5 h-5 text-gray-400" />
          : <ChevronDown className="w-5 h-5 text-gray-400" />
        }
      </button>

      {/* 内容区 */}
      {open && (
        <div className="px-5 pb-5 space-y-4 border-t border-gray-100">
          {/* 输入框 */}
          <div className="flex gap-2 mt-4">
            <input
              type="text"
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !loading && handlePlan()}
              placeholder="例如：为什么上周销售额下降了？哪些用户流失了？"
              className="flex-1 px-4 py-2.5 border border-gray-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent bg-white"
            />
            <button
              onClick={handlePlan}
              disabled={loading || !question.trim()}
              className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-violet-500 to-purple-600 text-white rounded-xl text-sm font-semibold disabled:opacity-50 hover:opacity-90 transition-all shadow-md shadow-violet-500/30"
            >
              {loading ? (
                <><Loader2 className="w-4 h-4 animate-spin" />规划中</>
              ) : (
                <>开始规划</>
              )}
            </button>
          </div>

          {/* 错误提示 */}
          {error && (
            <p className="text-sm text-red-600 bg-red-50 px-4 py-2 rounded-lg">{error}</p>
          )}

          {/* 规划结果 */}
          {plan && (
            <div className="space-y-3">
              {/* 分析目标 */}
              <div className="flex items-start gap-2 p-3 bg-violet-50 rounded-xl border border-violet-100">
                <span className="text-violet-600 text-sm">🎯</span>
                <p className="text-sm font-semibold text-violet-800">{plan.analysis_goal}</p>
              </div>

              {/* 步骤列表 */}
              <div className="space-y-2">
                {plan.steps?.map((step, idx) => (
                  <div
                    key={step.step}
                    className="flex items-start gap-3 p-4 bg-white rounded-xl border border-gray-200 hover:border-violet-200 hover:shadow-sm transition-all group"
                  >
                    {/* 步骤编号 */}
                    <span className="flex-shrink-0 w-6 h-6 bg-violet-500 text-white rounded-full flex items-center justify-center text-xs font-bold mt-0.5">
                      {step.step}
                    </span>

                    {/* 内容 */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-gray-800">{step.description}</p>
                      <p className="text-xs text-gray-500 mt-0.5">{step.why}</p>
                      <div className="mt-2 px-3 py-1.5 bg-violet-50 rounded-lg border border-violet-100">
                        <code className="text-xs text-violet-700 block truncate">{step.query}</code>
                      </div>
                    </div>

                    {/* 执行按钮 */}
                    <button
                      onClick={() => handleSelectQuery(step.query)}
                      className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 bg-violet-500 hover:bg-violet-600 text-white rounded-lg text-xs font-semibold transition-colors shadow-sm mt-0.5"
                    >
                      执行 <ArrowRight className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default QueryPlanner;
