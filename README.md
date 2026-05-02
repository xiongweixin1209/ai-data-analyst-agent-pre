# Text-to-SQL 智能数据查询 Agent

> 面向数据分析师的自然语言查询 Agent，通过中文提问自动生成并执行 SQL，整体执行成功率 82.5%，语法正确率 100%。

## 🌐 作者主页

**[xiongweixin1209.github.io](https://xiongweixin1209.github.io)**

---

## 项目简介

本项目是一个面向数据分析师的 **AI 驱动 SQL 查询工具**，核心产品问题是：降低 SQL 编写门槛的同时保障查询意图识别准确率。

用户用中文描述查询需求，系统自动生成、验证并执行 SQL，返回结构化结果与可视化图表。

---

## 技术架构

- **后端**：FastAPI + SQLAlchemy，支持 SQLite / MySQL 多数据源
- **前端**：React + Recharts，支持结果表格与自动图表切换
- **LLM**：Ollama 本地部署（Qwen2.5-Coder 7B），完全离线运行
- **分类器**：TF-IDF + Complement Naive Bayes，查询意图路由

---

## 核心功能

### 三层查询路由策略
基于 Naive Bayes 分类器将查询路由至三个策略层：

| 策略层 | 适用场景 | 说明 |
|---|---|---|
| 规则层 | 简单全表查询 | 无需 LLM，直接生成模板 SQL |
| Few-shot 层 | 过滤、聚合、JOIN | 检索最相关的 3 个示例注入 Prompt |
| Zero-shot 层 | 复杂嵌套、窗口函数 | 仅提供 Schema，依赖模型推理 |

### Few-shot 示例库
- 120 条覆盖 8 类查询意图的标注示例
- Jieba 倒排索引实现语义检索（keyword 权重 70%、query 文本 30%）

### AI 效果评估框架（`eval/`）
| 指标 | default 模式 | zero-shot-only | few-shot-top5 |
|---|---|---|---|
| LLM 调用成功率 | 100% | 100% | 100% |
| SQL 语法正确率 | 100% | 100% | 100% |
| 执行成功率（EX） | **82.5%** | 85.0% | 78.8% |
| 策略分类准确率 | 56.2% | — | — |
| 平均响应时间 | 3556ms | 3360ms | 3419ms |

评估测试集覆盖 8 类查询意图：单表查询、多表联结、聚合统计、时序查询、窗口函数、复杂嵌套、DWS 表查询、边界异常。

**核心发现：** 错误归因分析定位主要瓶颈为 schema 列名幻觉（占失败用例 85.7%）；Few-shot top-5 较 top-3 EX 下降 3.7%，验证检索精准度优先于召回数量的产品设计原则。

### 其他功能
- SQL 优化器（静态规则引擎：SELECT *、缺失 LIMIT、隐式类型转换等）
- EXPLAIN 性能分析与查询计划可视化
- 数据仓库分层可视化（ODS / DWD / DWS）
- 查询缓存（SHA-256 命中统计，持久化至 SQLite）
- LLM 驱动的字段注释自动生成

---

## 快速启动

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# 前端
cd frontend
npm install
npm run dev
```

需要本地运行 Ollama 并加载 `qwen2.5-coder:7b` 模型。

---

## 运行评估

```bash
# 快速测试（10条）
python eval/evaluator.py --limit 10 --mode default

# 全量三模式对比
python eval/evaluator.py

# 查看评估报告
cat eval/report.md
```

---

## 项目结构

```
text-to-sql/
├── backend/
│   ├── api/              # FastAPI 路由
│   └── services/         # 核心服务层
│       ├── text2sql_service.py   # 三层路由 + 分类器
│       ├── example_retriever.py  # Few-shot 检索
│       ├── prompts.py            # Prompt 模板
│       └── ...
├── frontend/             # React 前端
├── data/
│   ├── northwind.db      # Northwind 数据仓库
│   └── few_shot_examples.json  # 120 条标注示例
└── eval/
    ├── test_cases.json   # 80 条评估测试集
    ├── evaluator.py      # 评估脚本
    └── report.md         # 评估报告
```
