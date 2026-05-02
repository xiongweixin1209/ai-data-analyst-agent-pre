/**
 * SmartChart - 智能图表组件
 * 支持柱状图、折线图、饼图、面积图、散点图五种类型。
 * 自动根据数据结构和查询意图推断最合适的图表，用户可手动切换。
 */

import React, { useState, useEffect } from 'react';
import {
  BarChart, Bar,
  LineChart, Line,
  PieChart, Pie, Cell,
  AreaChart, Area,
  ScatterChart, Scatter,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer
} from 'recharts';

const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#3b82f6', '#ef4444', '#06b6d4'];

const CHART_TYPES = [
  { value: 'bar',     label: '柱状图' },
  { value: 'line',    label: '折线图' },
  { value: 'pie',     label: '饼图'   },
  { value: 'area',    label: '面积图' },
  { value: 'scatter', label: '散点图' },
];

/** 根据数据结构和查询意图推断图表类型 */
export function detectChartType(columns, data, queryIntent = '') {
  if (!columns || columns.length < 2 || !data || data.length === 0) return null;

  const col0 = columns[0];
  const sampleVal = String(data[0]?.[col0] ?? '');

  // 时间序列检测 → 折线图
  if (/\d{4}[-/年]\d{1,2}/.test(sampleVal) || /^\d{2}[-/]\d{2}/.test(sampleVal)) {
    return 'line';
  }

  // 占比/分布类关键词 → 饼图
  const pieKws = ['占比', '百分比', '比例', '分布', '构成', '份额'];
  if (pieKws.some(kw => queryIntent.includes(kw))) return 'pie';

  // 第一列也全是数字 → 散点图
  const col0AllNum = data.slice(0, 5).every(row => !isNaN(Number(row[col0])));
  const col1AllNum = data.slice(0, 5).every(row => !isNaN(Number(row[columns[1]])));
  if (col0AllNum && col1AllNum) return 'scatter';

  return 'bar';
}

// ------------------------------------------------------------------ //
// 子渲染函数
// ------------------------------------------------------------------ //

function renderBar(data, xKey, yKeys) {
  return (
    <BarChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 60 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
      <XAxis dataKey={xKey} tick={{ fontSize: 11 }} angle={-35} textAnchor="end" interval={0} />
      <YAxis tick={{ fontSize: 11 }} />
      <Tooltip />
      {yKeys.length > 1 && <Legend />}
      {yKeys.map((key, i) => (
        <Bar key={key} dataKey={key} fill={COLORS[i % COLORS.length]} radius={[4, 4, 0, 0]} />
      ))}
    </BarChart>
  );
}

function renderLine(data, xKey, yKeys) {
  return (
    <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 50 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
      <XAxis dataKey={xKey} tick={{ fontSize: 11 }} angle={-25} textAnchor="end" height={50} />
      <YAxis tick={{ fontSize: 11 }} />
      <Tooltip />
      {yKeys.length > 1 && <Legend />}
      {yKeys.map((key, i) => (
        <Line key={key} type="monotone" dataKey={key} stroke={COLORS[i % COLORS.length]}
          strokeWidth={2} dot={data.length < 30} activeDot={{ r: 5 }} />
      ))}
    </LineChart>
  );
}

function renderPie(data, xKey, yKey) {
  const pieData = data.map(row => ({ name: String(row[xKey] ?? ''), value: Number(row[yKey]) || 0 }));
  return (
    <PieChart>
      <Pie
        data={pieData} dataKey="value" nameKey="name"
        cx="50%" cy="50%" outerRadius={90}
        label={({ name, percent }) => `${name} ${(percent * 100).toFixed(1)}%`}
        labelLine={false}
      >
        {pieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
      </Pie>
      <Tooltip formatter={(val) => val.toLocaleString()} />
      <Legend />
    </PieChart>
  );
}

function renderArea(data, xKey, yKeys) {
  return (
    <AreaChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 50 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
      <XAxis dataKey={xKey} tick={{ fontSize: 11 }} angle={-25} textAnchor="end" height={50} />
      <YAxis tick={{ fontSize: 11 }} />
      <Tooltip />
      {yKeys.length > 1 && <Legend />}
      {yKeys.map((key, i) => (
        <Area key={key} type="monotone" dataKey={key}
          fill={COLORS[i % COLORS.length]} stroke={COLORS[i % COLORS.length]} fillOpacity={0.25} />
      ))}
    </AreaChart>
  );
}

function renderScatter(data, xKey, yKey) {
  return (
    <ScatterChart margin={{ top: 5, right: 20, left: 0, bottom: 20 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
      <XAxis dataKey={xKey} type="number" name={xKey} tick={{ fontSize: 11 }} />
      <YAxis dataKey={yKey} type="number" name={yKey} tick={{ fontSize: 11 }} />
      <Tooltip cursor={{ strokeDasharray: '3 3' }} />
      <Scatter data={data} fill={COLORS[0]} opacity={0.7} />
    </ScatterChart>
  );
}

// ------------------------------------------------------------------ //
// 主组件
// ------------------------------------------------------------------ //

const SmartChart = ({ data = [], columns = [], queryIntent = '' }) => {
  const autoType = detectChartType(columns, data, queryIntent);
  const [chartType, setChartType] = useState(autoType || 'bar');

  // queryIntent 变化时重新推断
  useEffect(() => {
    const t = detectChartType(columns, data, queryIntent);
    if (t) setChartType(t);
  }, [queryIntent, columns, data]);

  if (!autoType || columns.length < 2) return null;

  const xKey = columns[0];
  // 找出所有数值列作为 Y 轴（最多 3 条线）
  const yKeys = columns.slice(1)
    .filter(col => data.slice(0, 3).every(row => !isNaN(Number(row[col]))))
    .slice(0, 3);

  if (yKeys.length === 0) return null;

  const chartData = data.slice(0, 50);

  const renderChart = () => {
    switch (chartType) {
      case 'line':    return renderLine(chartData, xKey, yKeys);
      case 'pie':     return renderPie(chartData, xKey, yKeys[0]);
      case 'area':    return renderArea(chartData, xKey, yKeys);
      case 'scatter': return renderScatter(chartData, xKey, yKeys[0]);
      default:        return renderBar(chartData, xKey, yKeys);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">数据可视化</span>
        <div className="flex gap-1 flex-wrap">
          {CHART_TYPES.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setChartType(value)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                chartType === value
                  ? 'bg-indigo-500 text-white shadow-sm'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        {renderChart()}
      </ResponsiveContainer>
    </div>
  );
};

export default SmartChart;
