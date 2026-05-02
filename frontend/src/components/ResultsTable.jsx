/**
 * ResultsTable - 查询结果展示（增强版）
 * 新增：SmartChart 智能图表 + 报告导出（Markdown）
 */

import React, { useState, useMemo, useEffect, useRef } from 'react';
import {
  ArrowUpDown, ArrowUp, ArrowDown,
  Download, Filter, BarChart3, Hash, Clock,
  ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight,
  FileText, Copy, Check
} from 'lucide-react';
import SmartChart from './SmartChart';

const ResultsTable = ({
  data = [],
  columns = [],
  rowCount = 0,
  executionTime = 0,
  statistics = null,
  userQuery = '',
  sql = '',
}) => {
  const [sortConfig, setSortConfig] = useState({ key: null, direction: null });
  const [filters, setFilters] = useState({});
  const [showFilters, setShowFilters] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // AI 解读
  const [interpretation, setInterpretation] = useState('');
  const [interpretLoading, setInterpretLoading] = useState(false);
  const interpretedRef = useRef(false);

  // 报告复制状态
  const [reportCopied, setReportCopied] = useState(false);

  // 排序 & 筛选变化时重置分页
  useEffect(() => { setCurrentPage(1); }, [filters, sortConfig]);

  // 数据加载后自动获取 AI 解读
  useEffect(() => {
    if (!data?.length || !userQuery || interpretedRef.current) return;
    interpretedRef.current = true;

    const fetchInterpretation = async () => {
      setInterpretLoading(true);
      try {
        const res = await fetch('http://localhost:8000/api/text2sql/interpret', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_query: userQuery, columns, data: data.slice(0, 20) })
        });
        const result = await res.json();
        if (result.success) setInterpretation(result.interpretation);
      } catch (e) {
        console.error('AI 解读请求失败', e);
      } finally {
        setInterpretLoading(false);
      }
    };
    fetchInterpretation();
  }, [data, userQuery]);

  // 数据变化时重置解读
  useEffect(() => {
    setInterpretation('');
    interpretedRef.current = false;
  }, [userQuery]);

  // ---------------------------------------------------------------- //
  // 排序 & 筛选
  // ---------------------------------------------------------------- //

  const handleSort = (col) => {
    let dir = 'asc';
    if (sortConfig.key === col) {
      if (sortConfig.direction === 'asc') dir = 'desc';
      else { setSortConfig({ key: null, direction: null }); return; }
    }
    setSortConfig({ key: col, direction: dir });
  };

  const filteredAndSortedData = useMemo(() => {
    let result = [...data];
    if (Object.keys(filters).length) {
      result = result.filter(row =>
        Object.entries(filters).every(([key, val]) => {
          if (!val) return true;
          return String(row[key] ?? '').toLowerCase().includes(val.toLowerCase());
        })
      );
    }
    if (sortConfig.key) {
      result.sort((a, b) => {
        const av = a[sortConfig.key], bv = b[sortConfig.key];
        if (av == null) return 1;
        if (bv == null) return -1;
        const an = Number(av), bn = Number(bv);
        if (!isNaN(an) && !isNaN(bn)) return sortConfig.direction === 'asc' ? an - bn : bn - an;
        return sortConfig.direction === 'asc'
          ? String(av).localeCompare(String(bv))
          : String(bv).localeCompare(String(av));
      });
    }
    return result;
  }, [data, sortConfig, filters]);

  // ---------------------------------------------------------------- //
  // 分页
  // ---------------------------------------------------------------- //

  const paginationInfo = useMemo(() => {
    const total = filteredAndSortedData.length;
    const totalPages = Math.ceil(total / pageSize);
    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = Math.min(startIndex + pageSize, total);
    return { total, totalPages, startIndex, endIndex, hasNext: currentPage < totalPages, hasPrev: currentPage > 1 };
  }, [filteredAndSortedData, currentPage, pageSize]);

  const displayData = useMemo(() =>
    filteredAndSortedData.slice(paginationInfo.startIndex, paginationInfo.endIndex),
    [filteredAndSortedData, paginationInfo]
  );

  const getPageNumbers = () => {
    const { totalPages } = paginationInfo;
    if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1);
    const pages = [1];
    const start = Math.max(currentPage - 1, 2);
    const end = Math.min(currentPage + 1, totalPages - 1);
    if (start > 2) pages.push('...');
    for (let i = start; i <= end; i++) pages.push(i);
    if (end < totalPages - 1) pages.push('...');
    if (totalPages > 1) pages.push(totalPages);
    return pages;
  };

  // ---------------------------------------------------------------- //
  // 导出
  // ---------------------------------------------------------------- //

  const exportToCSV = () => {
    if (!filteredAndSortedData.length) return;
    const headers = columns.join(',');
    const rows = filteredAndSortedData.map(row =>
      columns.map(col => {
        const v = row[col];
        return String(v).includes(',') ? `"${v}"` : (v ?? '');
      }).join(',')
    ).join('\n');
    const blob = new Blob(['﻿' + headers + '\n' + rows], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `query_result_${Date.now()}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  /** 生成 Markdown 分析报告并复制到剪贴板 */
  const exportReport = async () => {
    const now = new Date().toLocaleString('zh-CN');
    const previewRows = filteredAndSortedData.slice(0, 10);

    const tableHeader = `| ${columns.join(' | ')} |`;
    const tableDivider = `| ${columns.map(() => '---').join(' | ')} |`;
    const tableRows = previewRows.map(row =>
      `| ${columns.map(col => String(row[col] ?? '')).join(' | ')} |`
    ).join('\n');

    const sqlBlock = sql ? `\`\`\`sql\n${sql}\n\`\`\`` : '（未记录 SQL）';
    const interpretBlock = interpretation || '（AI 解读生成中）';

    const markdown = `# 数据分析报告

**生成时间：** ${now}
**查询需求：** ${userQuery || '（未记录）'}

## 执行的 SQL

${sqlBlock}

## AI 分析结论

${interpretBlock}

## 数据摘要（共 ${filteredAndSortedData.length} 行，展示前 ${previewRows.length} 行）

${tableHeader}
${tableDivider}
${tableRows}
`;

    try {
      await navigator.clipboard.writeText(markdown);
      setReportCopied(true);
      setTimeout(() => setReportCopied(false), 2500);
    } catch (e) {
      console.error('复制失败', e);
    }
  };

  // ---------------------------------------------------------------- //
  // 排序图标
  // ---------------------------------------------------------------- //

  const getSortIcon = (col) => {
    if (sortConfig.key !== col) return <ArrowUpDown className="w-3.5 h-3.5 text-gray-400" />;
    return sortConfig.direction === 'asc'
      ? <ArrowUp className="w-3.5 h-3.5 text-blue-600" />
      : <ArrowDown className="w-3.5 h-3.5 text-blue-600" />;
  };

  // ---------------------------------------------------------------- //
  // 空状态
  // ---------------------------------------------------------------- //

  if (!data?.length) {
    return (
      <div className="text-center py-12 text-gray-400">
        <div className="w-16 h-16 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
          <BarChart3 className="w-8 h-8 text-gray-300" />
        </div>
        <p className="text-lg font-medium">暂无数据</p>
        <p className="text-sm mt-2">请执行查询获取结果</p>
      </div>
    );
  }

  // ---------------------------------------------------------------- //
  // 渲染
  // ---------------------------------------------------------------- //

  return (
    <div className="space-y-4">
      {/* 智能图表 */}
      <SmartChart data={data} columns={columns} queryIntent={userQuery} />

      {/* AI 解读 */}
      {(interpretLoading || interpretation) && (
        <div className="bg-gradient-to-r from-purple-50 to-blue-50 rounded-xl border border-purple-100 p-4">
          <p className="text-sm font-semibold text-purple-700 mb-1">🤖 AI 数据解读</p>
          {interpretLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <div className="w-3 h-3 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
              正在分析数据...
            </div>
          ) : (
            <p className="text-sm text-gray-700 leading-relaxed">{interpretation}</p>
          )}
        </div>
      )}

      {/* 统计信息 */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <StatCard icon={Hash} color="blue" label="返回行数"
          value={filteredAndSortedData.length}
          suffix={filteredAndSortedData.length !== rowCount ? `/ ${rowCount}` : ''} />
        <StatCard icon={BarChart3} color="purple" label="列数" value={columns.length} />
        <StatCard icon={Clock} color="green" label="执行时间" value={executionTime} suffix="ms" />
      </div>

      {/* 操作栏 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border text-sm transition-all ${
              showFilters ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
            }`}
          >
            <Filter className="w-3.5 h-3.5" />
            {showFilters ? '隐藏筛选' : '显示筛选'}
          </button>
          {(Object.values(filters).some(Boolean) || sortConfig.key) && (
            <button
              onClick={() => { setFilters({}); setSortConfig({ key: null, direction: null }); }}
              className="px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg border border-gray-300"
            >
              清除筛选/排序
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* 导出分析报告 */}
          <button
            onClick={exportReport}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border text-sm font-medium transition-all ${
              reportCopied
                ? 'bg-green-50 border-green-300 text-green-700'
                : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
            }`}
          >
            {reportCopied
              ? <><Check className="w-3.5 h-3.5" />已复制</>
              : <><FileText className="w-3.5 h-3.5" />导出报告</>
            }
          </button>

          <button
            onClick={exportToCSV}
            className="flex items-center gap-1.5 px-3 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg text-sm font-medium shadow-sm hover:opacity-90 transition-all"
          >
            <Download className="w-3.5 h-3.5" />导出 CSV
          </button>
        </div>
      </div>

      {/* 数据表格 */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gradient-to-r from-gray-50 to-gray-100 border-b border-gray-200">
              <tr>
                {columns.map(col => (
                  <th key={col} className="px-4 py-3 text-left">
                    <div className="flex flex-col gap-1.5">
                      <button
                        onClick={() => handleSort(col)}
                        className="flex items-center gap-1.5 text-xs font-semibold text-gray-700 hover:text-blue-600 transition-colors"
                      >
                        <span>{col}</span>
                        {getSortIcon(col)}
                      </button>
                      {showFilters && (
                        <input
                          type="text"
                          placeholder="筛选..."
                          value={filters[col] || ''}
                          onChange={e => setFilters(prev => ({ ...prev, [col]: e.target.value }))}
                          onClick={e => e.stopPropagation()}
                          className="px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                        />
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {displayData.map((row, i) => (
                <tr key={i} className="hover:bg-blue-50/40 transition-colors">
                  {columns.map(col => (
                    <td key={`${i}-${col}`} className="px-4 py-3 text-sm text-gray-700">
                      {row[col] ?? <span className="text-gray-400 italic">null</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {paginationInfo.totalPages > 1 && (
          <div className="px-4 py-3 bg-gray-50 border-t border-gray-200 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-3">
              <span className="text-sm text-gray-600">
                {paginationInfo.startIndex + 1}–{paginationInfo.endIndex} / {paginationInfo.total} 条
              </span>
              <select
                value={pageSize}
                onChange={e => { setPageSize(Number(e.target.value)); setCurrentPage(1); }}
                className="px-2 py-1.5 text-sm border border-gray-300 rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {[10, 25, 50, 100, 200].map(n => (
                  <option key={n} value={n}>{n} 条/页</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-1">
              <PageBtn onClick={() => setCurrentPage(1)} disabled={!paginationInfo.hasPrev} icon={<ChevronsLeft className="w-4 h-4" />} />
              <PageBtn onClick={() => setCurrentPage(p => p - 1)} disabled={!paginationInfo.hasPrev} icon={<ChevronLeft className="w-4 h-4" />} />
              {getPageNumbers().map((p, i) =>
                p === '...'
                  ? <span key={`e${i}`} className="px-2 text-gray-500">…</span>
                  : <button key={p} onClick={() => setCurrentPage(p)}
                      className={`min-w-[32px] px-2 py-1 rounded-lg text-sm font-medium transition-colors ${
                        currentPage === p ? 'bg-blue-600 text-white' : 'text-gray-700 hover:bg-gray-200'
                      }`}>{p}</button>
              )}
              <PageBtn onClick={() => setCurrentPage(p => p + 1)} disabled={!paginationInfo.hasNext} icon={<ChevronRight className="w-4 h-4" />} />
              <PageBtn onClick={() => setCurrentPage(paginationInfo.totalPages)} disabled={!paginationInfo.hasNext} icon={<ChevronsRight className="w-4 h-4" />} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

function StatCard({ icon: Icon, color, label, value, suffix = '' }) {
  const colors = {
    blue: 'from-blue-50 to-blue-100/50 border-blue-200/50 bg-blue-500 text-blue-600 text-blue-900',
    purple: 'from-purple-50 to-purple-100/50 border-purple-200/50 bg-purple-500 text-purple-600 text-purple-900',
    green: 'from-green-50 to-green-100/50 border-green-200/50 bg-green-500 text-green-600 text-green-900',
  };
  const [grad, border, bg, labelColor, valColor] = colors[color].split(' ');
  return (
    <div className={`bg-gradient-to-br ${grad} ${colors[color].split(' ')[1]} rounded-xl p-4 border ${border}`}>
      <div className="flex items-center gap-3">
        <div className={`w-9 h-9 ${bg} rounded-lg flex items-center justify-center`}>
          <Icon className="w-4 h-4 text-white" />
        </div>
        <div>
          <p className={`text-xs ${labelColor} font-medium`}>{label}</p>
          <p className={`text-xl font-bold ${valColor}`}>
            {value}
            {suffix && <span className={`text-sm ${labelColor} ml-1`}>{suffix}</span>}
          </p>
        </div>
      </div>
    </div>
  );
}

function PageBtn({ onClick, disabled, icon }) {
  return (
    <button onClick={onClick} disabled={disabled}
      className="p-1.5 rounded-lg hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-gray-600">
      {icon}
    </button>
  );
}

export default ResultsTable;
