/**
 * App.jsx - 主应用组件
 * Text-to-SQL 前端应用入口
 */

import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import { Database, FileText } from 'lucide-react';
import { AppProvider } from './context/AppContext';
import Text2SQLPage from './pages/Text2SQLPage';
import DataSourceManagement from './pages/DataSourceManagement';

// 导航栏组件
function Navigation() {
    const location = useLocation();

    const isActive = (path) => {
        return location.pathname === path;
    };

    return (
        <nav className="bg-white shadow-md border-b border-gray-200">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div className="flex justify-between h-16">
                    <div className="flex space-x-8">
                        {/* Logo/标题 */}
                        <div className="flex items-center">
                            <h1 className="text-xl font-bold text-gray-800">
                                Text-to-SQL System
                            </h1>
                        </div>

                        {/* 导航链接 */}
                        <div className="flex space-x-4 ml-10">
                            <Link
                                to="/"
                                className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                                    isActive('/')
                                        ? 'bg-blue-100 text-blue-700'
                                        : 'text-gray-700 hover:bg-gray-100'
                                }`}
                            >
                                <FileText className="w-4 h-4" />
                                SQL查询
                            </Link>

                            <Link
                                to="/datasource"
                                className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                                    isActive('/datasource')
                                        ? 'bg-blue-100 text-blue-700'
                                        : 'text-gray-700 hover:bg-gray-100'
                                }`}
                            >
                                <Database className="w-4 h-4" />
                                数据源管理
                            </Link>
                        </div>
                    </div>
                </div>
            </div>
        </nav>
    );
}

function App() {
    return (
        <Router>
            <AppProvider>
                <div className="App min-h-screen bg-gray-50">
                    <Navigation />
                    <Routes>
                        <Route path="/" element={<Text2SQLPage />} />
                        <Route path="/datasource" element={<DataSourceManagement />} />
                    </Routes>
                </div>
            </AppProvider>
        </Router>
    );
}

export default App;