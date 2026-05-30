/**
 * API Service - 数据源管理API扩展
 * 新增功能：上传、测试连接、刷新列表
 */

import axios from 'axios';

// API基础URL
const API_BASE_URL = 'http://localhost:8000/api';

// 创建axios实例
// timeout: 120s — 本地 Ollama 7B 模型生成长 JSON(/plan 等端点最多 1000 tokens)
// 在冷启动或负载高时可能要 30-60s,30s 全局超时会让前端先报错,导致后端
// 实际返回 200 但用户看到 "timeout" 的体验割裂。120s 给 LLM 充足时间。
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 响应拦截器 - 统一错误处理
apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
      console.error('API Error:', error);
      const errorMessage = error.response?.data?.detail
          || error.message
          || '请求失败';
      return Promise.reject(new Error(errorMessage));
    }
);

/**
 * Text-to-SQL API（原有，保持不变）
 */
export const text2sqlAPI = {
  // ... 原有代码保持不变 ...

  generate: async (query, schema, forceStrategy = null) => {
    const response = await apiClient.post('/text2sql/generate', {
      query,
      table_schema: schema,
      force_strategy: forceStrategy,
    });
    return response.data;
  },

  execute: async (params) => {
    const {
      query,
      sql,
      schema,
      datasourceId,
      includeOptimization = true,
    } = params;

    const requestData = {
      include_optimization: includeOptimization,
    };

    if (query) requestData.query = query;
    if (sql) requestData.sql = sql;
    if (schema) requestData.table_schema = schema;
    if (datasourceId) requestData.datasource_id = String(datasourceId);

    const response = await apiClient.post('/text2sql/execute', requestData);
    return response.data;
  },

  optimize: async (sql, schema = null) => {
    const requestData = { sql };
    if (schema) requestData.table_schema = schema;
    const response = await apiClient.post('/text2sql/optimize', requestData);
    return response.data;
  },

  analyze: async (sql, datasourceId = null) => {
    const requestData = { sql };
    if (datasourceId) requestData.datasource_id = String(datasourceId);
    const response = await apiClient.post('/text2sql/analyze', requestData);
    return response.data;
  },

  batchGenerate: async (queries, schema) => {
    const response = await apiClient.post('/text2sql/batch', {
      queries,
      table_schema: schema,
    });
    return response.data;
  },

  planAnalysis: async (businessQuestion, datasourceId = null) => {
    const body = { business_question: businessQuestion };
    if (datasourceId) body.datasource_id = String(datasourceId);
    const response = await apiClient.post('/text2sql/plan', body);
    return response.data;
  },

  recommendChart: async (queryIntent, columns, sampleData) => {
    const response = await apiClient.post('/text2sql/recommend-chart', {
      query_intent: queryIntent,
      columns,
      sample_data: sampleData,
    });
    return response.data;
  },

  getCacheStats: async (limit = 20) => {
    const response = await apiClient.get(`/text2sql/cache/stats?limit=${limit}`);
    return response.data;
  },

  health: async () => {
    const response = await apiClient.get('/text2sql/health');
    return response.data;
  },

  getExampleStats: async () => {
    const response = await apiClient.get('/text2sql/examples/stats');
    return response.data;
  },

  listDatasources: async () => {
    const response = await apiClient.get('/text2sql/datasources');
    return response.data;
  },

  getDatasourceSchema: async (datasourceId) => {
    const response = await apiClient.get(
        `/text2sql/datasources/${datasourceId}/schema`
    );
    return response.data;
  },
};

/**
 * 数据源管理API（增强版）
 */
export const datasourceAPI = {
  /**
   * 【新增】上传数据源文件
   * @param {File} file - 数据库文件
   * @param {string} name - 数据源名称（可选）
   * @param {Function} onProgress - 上传进度回调（可选）
   */
  upload: async (file, name = null, onProgress = null) => {
    const formData = new FormData();
    formData.append('file', file);
    if (name) formData.append('name', name);

    const response = await apiClient.post('/datasource/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percentCompleted = Math.round(
              (progressEvent.loaded * 100) / progressEvent.total
          );
          onProgress(percentCompleted);
        }
      },
    });

    return response.data;
  },

  /**
   * 【新增】测试数据源连接
   * @param {number} datasourceId - 数据源ID
   * @returns {Promise<Object>} 测试结果
   */
  testConnection: async (datasourceId) => {
    const response = await apiClient.post(`/datasource/${datasourceId}/test`);
    return response.data;
  },

  /**
   * 【新增】刷新数据源列表
   * @returns {Promise<Object>} 刷新结果
   */
  refresh: async () => {
    const response = await apiClient.post('/datasource/refresh');
    return response.data;
  },

  /**
   * 【新增】获取数据源列表（增强版，含状态）
   * @returns {Promise<Object>} 数据源列表
   */
  listEnhanced: async () => {
    const response = await apiClient.get('/datasource/list-enhanced');
    return response.data;
  },

  /**
   * 获取所有数据源列表（原有API）
   */
  list: async () => {
    const response = await apiClient.get('/datasource/list');
    return response.data;
  },

  /**
   * 获取数据库元信息（轻量级）
   * @param {number} datasourceId - 数据源ID
   */
  getMetadata: async (datasourceId) => {
    const response = await apiClient.get(`/datasource/${datasourceId}/metadata`);
    return response.data;
  },

  /**
   * 获取增强的Schema信息（完整）
   * @param {number} datasourceId - 数据源ID
   */
  getEnhancedSchema: async (datasourceId) => {
    const response = await apiClient.get(`/datasource/${datasourceId}/schema`);
    return response.data;
  },

  /**
   * 获取单个表的详细信息
   * @param {number} datasourceId - 数据源ID
   * @param {string} tableName - 表名
   */
  getTableDetail: async (datasourceId, tableName) => {
    const response = await apiClient.get(
        `/datasource/${datasourceId}/table/${tableName}`
    );
    return response.data;
  },

  /**
   * AI推荐合适的表
   * @param {number} datasourceId - 数据源ID
   * @param {string} userQuery - 用户查询需求
   */
  recommendTables: async (datasourceId, userQuery) => {
    const response = await apiClient.post(
        `/datasource/${datasourceId}/recommend-tables`,
        { user_query: userQuery }
    );
    return response.data;
  },

  /**
   * 添加数据源
   * @param {Object} datasource - 数据源信息
   */
  add: async (datasource) => {
    const response = await apiClient.post('/datasource/add', datasource);
    return response.data;
  },

  /**
   * 更新数据源
   * @param {number} datasourceId - 数据源ID
   * @param {Object} updates - 更新内容
   */
  update: async (datasourceId, updates) => {
    const response = await apiClient.put(`/datasource/${datasourceId}`, updates);
    return response.data;
  },

  /**
   * 删除数据源
   * @param {number} datasourceId - 数据源ID
   */
  delete: async (datasourceId) => {
    const response = await apiClient.delete(`/datasource/${datasourceId}`);
    return response.data;
  },

  /**
   * 获取单个数据源详情
   * @param {number} datasourceId - 数据源ID
   */
  get: async (datasourceId) => {
    const response = await apiClient.get(`/datasource/${datasourceId}`);
    return response.data;
  },

  /**
   * 获取默认数据源
   */
  getDefault: async () => {
    const response = await apiClient.get('/datasource/default/get');
    return response.data;
  },
};

/**
 * 示例数据源 Schema(开发参考用,不被任何组件 import)
 *
 * 注:命名风格刻意采用 PascalCase(Northwind 风格),原因有二:
 *  1. 跟项目主要 eval 目标 Northwind 数据集对齐
 *  2. 防止"示例 schema 污染" —— 历史上这里曾用 snake_case
 *     (invoice_no/stock_code 等),即便不被 import,也不应在仓库里
 *     留下错误命名约定作为"参考"。
 */
export const demoSchema = [
  {
    table_name: 'Orders',
    columns: [
      { name: 'OrderID',     type: 'INTEGER' },
      { name: 'CustomerID',  type: 'TEXT' },
      { name: 'OrderDate',   type: 'TEXT' },
      { name: 'ShipCountry', type: 'TEXT' },
      { name: 'Freight',     type: 'REAL' },
    ],
  },
  {
    table_name: 'Customers',
    columns: [
      { name: 'CustomerID',  type: 'TEXT' },
      { name: 'CompanyName', type: 'TEXT' },
      { name: 'ContactName', type: 'TEXT' },
      { name: 'Country',     type: 'TEXT' },
      { name: 'City',        type: 'TEXT' },
    ],
  },
];

export default apiClient;