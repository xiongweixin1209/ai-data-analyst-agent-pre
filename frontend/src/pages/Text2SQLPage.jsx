/**
 * Text2SQL Page - 主页面
 * 数据源 / Schema 状态来自 AppContext，消除 prop drilling。
 */

import React, { useState, useEffect } from 'react';
import { Search, Sparkles, BarChart3, Lightbulb, Layers, Database } from 'lucide-react';
import { text2sqlAPI } from '../services/api';
import { useApp } from '../context/AppContext';
import QueryInput from '../components/QueryInput';
import SQLDisplay from '../components/SQLDisplay';
import ResultsTable from '../components/ResultsTable';
import OptimizationPanel from '../components/OptimizationPanel';
import PerformancePanel from '../components/PerformancePanel';
import LoadingSpinner from '../components/LoadingSpinner';
import DatabaseCognition from '../components/DatabaseCognition';
import QueryPlanner from '../components/QueryPlanner';

const Text2SQLPage = () => {
  // 全局状态（来自 Context）
  const {
    datasources,
    selectedDatasource,
    setSelectedDatasource,
    datasourceSchema,
    loadingSchema,
  } = useApp();

  // 主 Tab
  const [mainTab, setMainTab] = useState('query');

  // 表选择
  const [selectedTables, setSelectedTables] = useState([]);
  const [showTableSelector, setShowTableSelector] = useState(false);

  // 查询相关
  const [query, setQuery] = useState('');
  const [sql, setSql] = useState('');
  const [results, setResults] = useState(null);
  const [optimization, setOptimization] = useState(null);
  const [performance, setPerformance] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('results');

  // 切换数据源时清空已选表
  useEffect(() => {
    setSelectedTables([]);
    setShowTableSelector(false);
  }, [selectedDatasource]);

  // 从数据库结构 Tab 跳转过来时预选表
  const handleJumpFromDatabase = (datasourceId, tableNames) => {
    setMainTab('query');
    setSelectedDatasource(datasourceId);
    setTimeout(() => {
      setSelectedTables(tableNames);
      setShowTableSelector(true);
    }, 500);
  };

  const toggleTableSelection = (tableName) => {
    setSelectedTables(prev =>
      prev.includes(tableName) ? prev.filter(t => t !== tableName) : [...prev, tableName]
    );
  };

  const getFilteredSchema = () => {
    if (!datasourceSchema?.table_details) return [];
    const all = datasourceSchema.table_details.map(t => ({
      table_name: t.table_name,
      columns: t.columns
    }));
    if (selectedTables.length > 0) {
      return all.filter(t => selectedTables.includes(t.table_name));
    }
    return all;
  };

  // 生成 SQL
  const handleGenerate = async () => {
    if (!query.trim()) { setError('请输入查询语句'); return; }
    if (!datasourceSchema) { setError('请先选择数据源'); return; }

    setLoading(true); setError(null); setSql('');
    try {
      const schema = getFilteredSchema();
      const response = await text2sqlAPI.generate(query, schema);
      if (response.success) { setSql(response.sql); }
      else { setError(response.error || 'SQL 生成失败'); }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // 执行 SQL
  const handleExecute = async () => {
    if (!query.trim() && !sql.trim()) { setError('请输入查询语句或 SQL'); return; }
    if (!selectedDatasource) { setError('请先选择数据源'); return; }

    setLoading(true); setError(null); setResults(null); setOptimization(null);
    try {
      const schema = getFilteredSchema();
      const response = await text2sqlAPI.execute({
        query: query || null,
        sql: sql || null,
        schema,
        datasourceId: selectedDatasource,
        includeOptimization: true,
      });

      if (response.success) {
        setSql(response.sql);
        setResults({
          data: response.data,
          columns: response.columns,
          rowCount: response.row_count,
          executionTime: response.execution_time,
        });
        setOptimization(response.optimization);
        setActiveTab('results');
      } else {
        setError(response.error || 'SQL 执行失败');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // 优化分析
  const handleOptimize = async () => {
    if (!sql.trim()) { setError('请先生成 SQL'); return; }
    setLoading(true); setError(null);
    try {
      const schema = getFilteredSchema();
      const response = await text2sqlAPI.optimize(sql, schema);
      setOptimization(response);
      setActiveTab('optimize');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // 性能分析
  const handleAnalyze = async () => {
    if (!sql.trim()) { setError('请先生成 SQL'); return; }
    setLoading(true); setError(null);
    try {
      const response = await text2sqlAPI.analyze(sql, selectedDatasource);
      setPerformance(response);
      setActiveTab('analyze');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setQuery(''); setSql(''); setResults(null);
    setOptimization(null); setPerformance(null);
    setError(null); setActiveTab('results'); setSelectedTables([]);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-indigo-100 animate-fadeIn">
      <div className="max-w-[1600px] mx-auto px-4 py-8 sm:px-6 lg:px-8">

        {/* 头部 */}
        <header className="mb-10 text-center animate-slideIn">
          <div className="inline-flex items-center justify-center mb-6">
            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-br from-blue-400 to-indigo-600 rounded-3xl blur-xl opacity-50 animate-pulse-soft"></div>
              <div className="relative w-20 h-20 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-3xl flex items-center justify-center shadow-2xl shadow-blue-500/30 transform hover:scale-110 transition-transform duration-300">
                <Search className="w-10 h-10 text-white" />
              </div>
            </div>
          </div>
          <h1 className="text-5xl sm:text-6xl font-bold bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 bg-clip-text text-transparent mb-4 animate-gradient">
            Text-to-SQL Assistant
          </h1>
          <p className="text-gray-600 text-lg font-medium mb-6">
            自然语言转SQL · 智能执行 · 性能优化
          </p>
          <div className="flex justify-center gap-3 mt-8">
            <button
              onClick={() => setMainTab('query')}
              className={`flex items-center gap-2 px-6 py-3 rounded-xl font-semibold transition-all duration-300 ${
                mainTab === 'query'
                  ? 'bg-gradient-to-r from-blue-500 to-indigo-600 text-white shadow-lg shadow-blue-500/30 scale-105'
                  : 'bg-white/80 text-gray-600 hover:bg-white hover:shadow-md hover:scale-105'
              }`}
            >
              <Search className="w-5 h-5" />SQL查询
            </button>
            <button
              onClick={() => setMainTab('database')}
              className={`flex items-center gap-2 px-6 py-3 rounded-xl font-semibold transition-all duration-300 ${
                mainTab === 'database'
                  ? 'bg-gradient-to-r from-green-500 to-emerald-600 text-white shadow-lg shadow-green-500/30 scale-105'
                  : 'bg-white/80 text-gray-600 hover:bg-white hover:shadow-md hover:scale-105'
              }`}
            >
              <Layers className="w-5 h-5" />数据库结构
            </button>
          </div>
        </header>

        {mainTab === 'query' ? (
          <>
            {/* 分析规划（阶段二）*/}
            <QueryPlanner
              datasourceId={selectedDatasource}
              onSelectQuery={(q) => { setQuery(q); }}
            />

            {/* 数据源和表选择 */}
            <div className="mb-6 backdrop-blur-sm bg-white/80 rounded-2xl shadow-lg border border-gray-200/50 p-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
                    <Database className="w-4 h-4" />选择数据源
                  </label>
                  <select
                    value={selectedDatasource || ''}
                    onChange={(e) => setSelectedDatasource(Number(e.target.value))}
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                    disabled={loadingSchema}
                  >
                    {datasources.map(ds => (
                      <option key={ds.id} value={ds.id}>{ds.name} ({ds.type})</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
                    <Sparkles className="w-4 h-4" />指定查询表（可选）
                  </label>
                  <button
                    onClick={() => setShowTableSelector(!showTableSelector)}
                    className={`w-full px-4 py-3 rounded-lg font-medium transition-all ${
                      showTableSelector
                        ? 'bg-blue-500 text-white hover:bg-blue-600'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200 border border-gray-300'
                    }`}
                    disabled={!datasourceSchema}
                  >
                    {showTableSelector ? '已展开表选择器' : '点击展开表选择器'}
                    {selectedTables.length > 0 && (
                      <span className="ml-2 bg-white/20 px-2 py-0.5 rounded-full text-xs">
                        已选 {selectedTables.length} 张表
                      </span>
                    )}
                  </button>
                </div>
              </div>

              {showTableSelector && datasourceSchema && (
                <div className="mt-6 p-4 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-lg border border-blue-200">
                  <p className="text-sm font-medium text-gray-700 mb-3">
                    选择要查询的表（可多选，不选则使用所有表）：
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2 max-h-48 overflow-y-auto">
                    {datasourceSchema.table_details?.map(table => (
                      <label
                        key={table.table_name}
                        className={`flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all ${
                          selectedTables.includes(table.table_name)
                            ? 'bg-blue-500 text-white shadow-md'
                            : 'bg-white text-gray-700 hover:bg-blue-100 border border-gray-300'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={selectedTables.includes(table.table_name)}
                          onChange={() => toggleTableSelection(table.table_name)}
                          className="sr-only"
                        />
                        <span className="text-sm font-medium truncate">{table.table_name}</span>
                        {table.layer === 'DWS' && <span className="text-xs">⚡</span>}
                      </label>
                    ))}
                  </div>
                  {selectedTables.length > 0 && (
                    <div className="mt-3 flex items-center justify-between text-sm">
                      <span className="text-blue-700 font-medium">
                        已选择 {selectedTables.length} 张表: {selectedTables.join(', ')}
                      </span>
                      <button
                        onClick={() => setSelectedTables([])}
                        className="text-blue-600 hover:text-blue-800 underline"
                      >清空选择</button>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* 主内容区 */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
              {/* 左：输入 */}
              <div className="space-y-6">
                <QueryInput
                  value={query} onChange={setQuery}
                  onGenerate={handleGenerate} onExecute={handleExecute}
                  onClear={handleClear} loading={loading}
                />
                <SQLDisplay
                  sql={sql} onChange={setSql}
                  onOptimize={handleOptimize} onAnalyze={handleAnalyze}
                  loading={loading}
                />
                {error && (
                  <div className="backdrop-blur-sm bg-red-50/80 border-l-4 border-red-500 rounded-xl p-5 shadow-lg shadow-red-100/50 animate-shake">
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0">
                        <div className="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center">
                          <svg className="h-5 w-5 text-red-600" viewBox="0 0 20 20" fill="currentColor">
                            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                          </svg>
                        </div>
                      </div>
                      <div className="flex-1">
                        <p className="text-sm font-semibold text-red-900">错误</p>
                        <p className="text-sm text-red-700 mt-1">{error}</p>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* 右：结果 */}
              <div className="space-y-6">
                <div className="backdrop-blur-sm bg-white/80 rounded-2xl shadow-xl shadow-blue-100/50 border border-gray-200/50 overflow-hidden">
                  <div className="border-b border-gray-200/50 bg-gradient-to-r from-gray-50/80 to-white/80 backdrop-blur-sm">
                    <nav className="flex -mb-px">
                      {[
                        { key: 'results', label: '查询结果', icon: BarChart3, color: 'blue', badge: results?.rowCount },
                        { key: 'optimize', label: '优化建议', icon: Sparkles, color: 'orange', badge: optimization?.suggestions?.length, disabled: !optimization },
                        { key: 'analyze', label: '性能分析', icon: BarChart3, color: 'purple', disabled: !performance },
                      ].map(({ key, label, icon: Icon, color, badge, disabled }) => (
                        <button
                          key={key}
                          onClick={() => setActiveTab(key)}
                          disabled={disabled}
                          className={`group relative px-6 py-4 font-medium text-sm transition-all duration-300 ${
                            activeTab === key ? `text-${color}-600` : 'text-gray-500 hover:text-gray-700'
                          }`}
                        >
                          <span className="flex items-center gap-2">
                            <Icon className={`w-4 h-4 transition-transform duration-300 ${activeTab === key ? 'scale-110' : 'group-hover:scale-110'}`} />
                            {label}
                            {badge != null && (
                              <span className={`bg-${color}-100 text-${color}-600 px-2 py-0.5 rounded-full text-xs font-semibold animate-scaleIn`}>
                                {badge}
                              </span>
                            )}
                          </span>
                          {activeTab === key && (
                            <div className={`absolute bottom-0 left-0 right-0 h-1 bg-gradient-to-r from-${color}-500 to-${color === 'orange' ? 'red' : color === 'purple' ? 'pink' : 'indigo'}-500 rounded-t-full`} />
                          )}
                        </button>
                      ))}
                    </nav>
                  </div>

                  <div className="p-6 min-h-[600px] bg-white/50 backdrop-blur-sm">
                    {loading && (
                      <div className="flex justify-center items-center h-full">
                        <LoadingSpinner />
                      </div>
                    )}

                    {!loading && activeTab === 'results' && (
                      <div className="animate-fadeIn">
                        {results ? (
                          <ResultsTable
                            data={results.data} columns={results.columns}
                            rowCount={results.rowCount} executionTime={results.executionTime}
                            userQuery={query} sql={sql}
                          />
                        ) : (
                          <EmptyState icon={BarChart3} title="等待查询执行" desc="输入查询并点击「执行」查看结果" color="blue" />
                        )}
                      </div>
                    )}

                    {!loading && activeTab === 'optimize' && (
                      <div className="animate-fadeIn">
                        {optimization ? (
                          <OptimizationPanel optimization={optimization} />
                        ) : (
                          <EmptyState icon={Sparkles} title="等待优化分析" desc="点击「优化分析」查看 SQL 优化建议" color="orange" />
                        )}
                      </div>
                    )}

                    {!loading && activeTab === 'analyze' && (
                      <div className="animate-fadeIn">
                        {performance ? (
                          <PerformancePanel performance={performance} />
                        ) : (
                          <EmptyState icon={BarChart3} title="等待性能分析" desc="点击「性能分析」查看详细报告" color="purple" />
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* 示例查询 */}
            <div className="mt-10 backdrop-blur-sm bg-white/80 rounded-2xl shadow-lg shadow-blue-100/50 border border-gray-200/50 p-8 animate-fadeIn">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 bg-gradient-to-br from-yellow-400 to-orange-500 rounded-xl flex items-center justify-center">
                  <Lightbulb className="w-6 h-6 text-white" />
                </div>
                <h3 className="text-xl font-bold bg-gradient-to-r from-gray-700 to-gray-900 bg-clip-text text-transparent">
                  快速示例
                </h3>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {[
                  '查询所有订单',
                  '查询数量大于10的订单',
                  '统计每个国家的订单数量',
                  '查询销售额最高的前10个商品',
                  '查询英国的订单，按日期排序',
                  '计算2010年12月的总销售额',
                ].map((example, index) => (
                  <button
                    key={index}
                    onClick={() => setQuery(example)}
                    className="group relative text-left px-5 py-4 backdrop-blur-sm bg-gradient-to-br from-gray-50/80 to-white/80 hover:from-blue-50/80 hover:to-indigo-50/80 border border-gray-200/50 hover:border-blue-300/50 rounded-xl transition-all duration-300 text-sm text-gray-700 hover:text-blue-600 shadow-sm hover:shadow-lg hover:shadow-blue-100/50 transform hover:-translate-y-1 active:scale-95"
                  >
                    <span className="group-hover:translate-x-1 inline-block transition-transform duration-300">
                      {example}
                    </span>
                    <div className="absolute top-2 right-2 w-2 h-2 bg-blue-400 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
                  </button>
                ))}
              </div>
            </div>
          </>
        ) : (
          <div className="animate-fadeIn">
            <DatabaseCognition onJumpToQuery={handleJumpFromDatabase} />
          </div>
        )}
      </div>
    </div>
  );
};

function EmptyState({ icon: Icon, title, desc, color }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-gray-400 py-20">
      <div className="relative mb-6">
        <div className={`absolute inset-0 bg-gradient-to-br from-${color}-200 to-${color}-200 rounded-full blur-2xl opacity-30 animate-pulse-soft`}></div>
        <div className={`relative w-28 h-28 bg-gradient-to-br from-${color}-100 to-${color}-100 rounded-full flex items-center justify-center`}>
          <Icon className={`w-14 h-14 text-${color}-400`} />
        </div>
      </div>
      <p className="text-lg font-semibold text-gray-600 mb-2">{title}</p>
      <p className="text-sm text-gray-500">{desc}</p>
    </div>
  );
}

export default Text2SQLPage;
