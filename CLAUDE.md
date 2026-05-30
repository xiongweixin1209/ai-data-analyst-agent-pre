# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Text-to-SQL Assistant — a local AI data analysis tool. Users describe queries in natural language; the system generates SQL via a 3-layer strategy, executes it, and returns results with chart visualization and AI business interpretation. The entire pipeline runs locally using Ollama (no cloud dependency).

## Running the Project

**Prerequisites:** Python 3.10+, Node.js 18+, Ollama running locally with `qwen2.5-coder:7b` pulled.

```bash
# Pull the LLM model (one-time)
ollama pull qwen2.5-coder:7b

# Backend (from backend/)
pip install -r requirements.txt
python main.py
# → http://localhost:8000  |  API docs: http://localhost:8000/docs

# Frontend (from frontend/)
npm install
npm run dev
# → http://localhost:5173
```

没有 pytest 套件,但有两种自测路径:

1. **服务模块自带 smoke test** — 每个 service 文件的 `if __name__ == "__main__":` 块:
   ```bash
   cd backend
   python services/llm_service.py           # 测试 Ollama 连通性
   python services/example_retriever.py    # 测试 few-shot 检索
   python services/text2sql_service.py     # 测试端到端 SQL 生成
   python services/sql_validator.py        # 测试 SQL 校验(CTE / UNION ALL / 危险关键词)
   python services/sql_optimizer.py        # 测试优化规则
   ```

2. **离线评估框架** — 跑全部三模式对比(需 Ollama 启动 + Northwind db):
   ```bash
   python eval/evaluator.py                # 三模式全跑,写入 eval/report.md
   python eval/evaluator.py --limit 10     # 快速冒烟
   ```

## Architecture

### Backend (`backend/`)

The backend is a FastAPI app with three route groups registered in `main.py`:
- `/api/datasource` — datasource CRUD, file upload, connection testing, schema + table detail
- `/api/schema` — (thin wrapper, mostly absorbed into datasource routes)
- `/api/text2sql` — generate, execute, optimize, analyze, batch, interpret

**Service layer** (the real logic lives here):

| Service | Responsibility |
|---|---|
| `text2sql_service.py` | 3-layer strategy router (rule/few_shot/zero_shot) + Naive Bayes classifier + business interpretation via LLM |
| `llm_service.py` | Ollama HTTP wrapper; extracts SQL from `\`\`\`sql` blocks |
| `schema_service.py` | Schema reading, DWD/DWS layer detection, domain classification, LLM table recommendation |
| `example_retriever.py` | jieba 分词 + 倒排索引 over `data/few_shot_examples.json` (no vector DB) |
| `sql_executor.py` | SQLite SQL execution with timeout, read-only mode |
| `sql_optimizer.py` | Pluggable rule registry — pure regex/sqlparse static analysis, no LLM |
| `sql_validator.py` | Token-based safety check (allows SELECT/WITH, blocks DML/DDL/file functions); 不再使用子串匹配以避免误伤含 `CREATED_AT` 等列名的查询 |
| `query_performance_analyzer.py` | EXPLAIN plan parsing |
| `datasource_manager.py` | Singleton registry mapping datasource IDs to executors; 启动时从 app.db 加载,带 schema TTL 缓存 |
| `field_comment_service.py` | LLM 自动推断表/字段中文业务注释,持久化到 app.db 的 `field_comments` 表 |
| `query_cache_service.py` | 持久化查询缓存,key = `(query, datasource_id, schema指纹, force_strategy)` 的 MD5,记录命中次数 |

**Data model:** `DataSource` ORM + `query_cache` + `field_comments` 表存在 `backend/data/app.db`。用户上传的源 db 单独存放,路径登记在 datasources 表里。

### 3-Layer SQL Generation Strategy

`text2sql_service.py` 用 **TF-IDF + Complement Naive Bayes** 分类器把 query 路由到三层之一(启动时基于 few_shot_examples.json 训练,分类失败回退到关键词规则):

1. **Rule layer** — 极简查询("查询所有..."),返回 `SELECT * FROM <schema[0].table_name> LIMIT 100`,零 LLM 调用。首表无名时降级到 few-shot
2. **Few-shot layer** — 聚合 / 过滤 / JOIN 查询;倒排索引检索 top-3 示例 → 构建 prompt → Ollama temp=0.1
3. **Zero-shot layer** — 复杂嵌套 / 窗口 / 排名 / 占比;仅注入 schema → Ollama temp=0.2

`text2sql_routes.py:/execute` 路由还在 LLM 前查询缓存:命中直接返回缓存 SQL。缓存键含 schema 指纹,因此同一句话不同 schema 不会互串。

### Few-shot Example Library

`data/few_shot_examples.json` — 120 条,字段 `query / sql / keywords / category / difficulty`。检索用 jieba 分词后做关键词交集打分(keywords 字段 70% 权重,query 文本 30%),底层维护倒排索引避免全量扫描。无 embedding/向量库。

### 评估框架 (`eval/`)

- `eval/test_cases.json` — 80 条 Northwind 测试用例,覆盖 8 类查询意图、4 个难度等级
- `eval/evaluator.py` — 离线评估脚本,支持 `default`、`zero_shot_only`、`few_shot_top5` 三种模式对比
- `eval/report.md` — 自动生成的评估报告(EX 成功率 / 语法正确率 / 策略准确率 / 失败用例列表)
- 注意:eval 的 SELECT/WITH 检查独立于 `sql_validator.py`,以前两者对 CTE 的接受度不一致(`sql_validator.py` 现已支持 WITH)

### Schema Cognition (DWD/DWS Detection)

`schema_service.py::detect_layer()` applies three methods in order:
1. Query `table_metadata` table if present in the DB
2. Check for `dws_` / `dwd_` naming prefix
3. Keyword heuristics (`summary`, `daily`, `agg`, etc. → DWS)

`analyze_domain()` similarly maps table names to 7 business domains (订单域, 客户域, 产品域, 员工域, 供应商域, 物流域, 其他).

### Frontend (`frontend/src/`)

Single-page app with两个顶级 view 由 `Text2SQLPage.jsx` 的 `mainTab` 切换:
- **SQL查询** — 数据源选择 → 可选表多选 → 自然语言输入 → SQL 展示 → 三个 tab (results / optimize / analyze)
- **数据库结构** — `DatabaseCognition.jsx`,展示 DWD/DWS 分层、业务域、AI 表推荐,支持一键跳转到 SQL查询 并预选相关表

关键组件:
- `Text2SQLPage.jsx` — 主页面,从 `AppContext` 取数据源/Schema,内含静态 `TAB_COLORS` / `EMPTY_COLORS` 映射(Tailwind JIT 不识别运行时模板字符串,所以 color → class 全部预映射)
- `SmartChart.jsx` — 客户端图表渲染器,接受 `/recommend-chart` 返回的类型,内部还会基于列数据类型再校验一次;失败回退到表格
- `ResultsTable.jsx` — 结果表格 + 排序/筛选 + CSV 导出(写 `﻿` BOM 保证 Excel 中文正确)+ 调用 `/interpret` 取 AI 解读
- `QueryPlanner.jsx` — 业务问题→子查询步骤拆解,调用 `/api/text2sql/plan`,折叠展示步骤卡片
- `AppContext.jsx` — 全局 datasource / schema 状态,消除 prop drilling

API 调用统一走 `frontend/src/services/api.js`(axios,base URL `http://localhost:8000/api`)。

### Key Configuration

`backend/config.py` (via `backend/.env`):
- `OLLAMA_MODEL` — default `qwen2.5-coder:7b`
- `DEMO_DB_PATH` — resolves to `../data/demo_ecommerce.db`
- `FEW_SHOT_PATH` — resolves to `../data/few_shot_examples.json`
- `AUTO_MODE_MAX_TABLES` / `AUTO_MODE_MAX_COLUMNS` — thresholds for auto/smart/manual query mode

### Pydantic v2 Compatibility

`text2sql_routes.py` contains a `convert_schema_to_dict()` helper that manually converts Pydantic model lists to dicts before passing them to service layer functions. This is required because service functions accept plain `List[Dict]`, not Pydantic models. When adding new routes that pass schema through, always call this converter.

## Demo Databases

**注意:`.db` 文件不在 git 中**(看 `.gitignore`),仅在本地工作目录存在。首次 clone 后需运行 `python backend/create_demo_db.py` 或自行准备。

**目录职责**:
- `data/` — 所有业务/示例数据库 + few-shot 资料(可被自动扫描注册)
- `backend/data/` — 仅放应用元数据(`app.db`)

| File | Contents |
|---|---|
| `data/demo_ecommerce.db` | E-commerce orders,默认 demo 目标(`settings.DEMO_DB_PATH`) |
| `data/northwind.db` | Northwind 数仓 — 16 张表,DWD/DWS 分层,7 个业务域,**eval 用的就是这个** |
| `data/Chinook_Sqlite_*.sqlite` | 音乐商店示例 db |
| `data/few_shot_examples.json` | 120 条 few-shot 示例 |
| `backend/data/app.db` | 应用元数据库:datasources / query_cache / field_comments |

### 数据源自动注册机制

`datasource_manager.py` 启动时做三件事(在 `__init__` 里依次跑):

1. **从 app.db 加载**(`_load_all_from_db`)— 把 `datasources` 表里已有记录加载到内存
2. **扫盘自动注册**(`_auto_register_from_disk`)— 扫描 `data/` 与 `settings.EXTERNAL_DATA_DIRS` 配置的每个目录,把发现的 `*.db / *.sqlite / *.sqlite3` 文件且未注册的自动 INSERT 进 datasources 表
3. **幽灵记录检测**(`_check_ghost_records`)— 检查所有 `file_path` 字段指向的文件是否存在,不存在的打印警告但**不删除**(温和策略,允许用户手动恢复或清理)

去重依据:`file_path` 解析为绝对路径后作为唯一键。已注册的文件不会被重复 INSERT,启动是幂等的。

为 Plan C 等外部数据仓库对接预留的扩展点是 `settings.EXTERNAL_DATA_DIRS`,在 `config.py` 或 `.env` 里配置一个绝对路径列表,启动时会一起扫描。
