/**
 * AppContext - 全局状态管理
 * 管理跨组件共享的数据源、Schema 等状态，消除 prop drilling。
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { datasourceAPI } from '../services/api';

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [datasources, setDatasources] = useState([]);
  const [selectedDatasource, setSelectedDatasource] = useState(null);
  const [datasourceSchema, setDatasourceSchema] = useState(null);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [schemaError, setSchemaError] = useState(null);

  const loadDatasources = useCallback(async () => {
    try {
      const response = await datasourceAPI.list();
      const items = response.items || [];
      setDatasources(items);
      if (items.length > 0 && !selectedDatasource) {
        setSelectedDatasource(items[0].id);
      }
    } catch (err) {
      console.error('加载数据源失败:', err);
    }
  }, [selectedDatasource]);

  const loadDatasourceSchema = useCallback(async (datasourceId) => {
    if (!datasourceId) return;
    setLoadingSchema(true);
    setSchemaError(null);
    try {
      const schema = await datasourceAPI.getEnhancedSchema(datasourceId);
      setDatasourceSchema(schema);
    } catch (err) {
      console.error('加载 Schema 失败:', err);
      setDatasourceSchema(null);
      setSchemaError('加载数据库结构失败，请检查数据源连接');
    } finally {
      setLoadingSchema(false);
    }
  }, []);

  // 初始化时加载数据源列表
  useEffect(() => {
    loadDatasources();
  }, []);

  // 数据源切换时自动加载 schema
  useEffect(() => {
    if (selectedDatasource) {
      loadDatasourceSchema(selectedDatasource);
    }
  }, [selectedDatasource, loadDatasourceSchema]);

  const refreshDatasources = () => loadDatasources();

  const value = {
    // 数据源
    datasources,
    selectedDatasource,
    setSelectedDatasource,
    refreshDatasources,
    // Schema
    datasourceSchema,
    setDatasourceSchema,
    loadingSchema,
    schemaError,
    loadDatasourceSchema,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp 必须在 AppProvider 内使用');
  return ctx;
}
