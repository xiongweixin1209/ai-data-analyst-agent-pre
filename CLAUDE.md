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

There are no automated test suites in this codebase. Each service module has a standalone `if __name__ == "__main__":` test block that can be run directly:

```bash
cd backend
python services/llm_service.py           # Test Ollama connection
python services/example_retriever.py    # Test few-shot retrieval
python services/text2sql_service.py     # Test end-to-end SQL generation
python services/sql_optimizer.py        # Test optimizer rules
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
| `text2sql_service.py` | 3-layer strategy router + business interpretation via LLM |
| `llm_service.py` | Ollama HTTP wrapper; extracts SQL from `\`\`\`sql` blocks |
| `schema_service.py` | Schema reading, DWD/DWS layer detection, domain classification, LLM table recommendation |
| `example_retriever.py` | Keyword-similarity retrieval over `data/few_shot_examples.json` (no vector DB) |
| `sql_executor.py` | Multi-datasource SQL execution with timeout |
| `sql_optimizer.py` | Pure regex/AST static analysis — no LLM needed |
| `query_performance_analyzer.py` | EXPLAIN plan parsing |
| `datasource_manager.py` | Singleton registry mapping datasource IDs to executors |

**Data model:** `DataSource` ORM model stored in `data/app.db` (SQLite). The registered datasources point to separate `.db` files (`demo_ecommerce.db`, `northwind.db`, etc.).

### 3-Layer SQL Generation Strategy

`text2sql_service.py` classifies every incoming query by keyword matching, then routes:

1. **Rule layer** — ultra-simple queries ("查询所有..."), returns hardcoded `SELECT * FROM <first_table> LIMIT 100` with zero LLM calls
2. **Few-shot layer** — aggregation or filter queries; retrieves top-3 examples from the 120-example library, builds a structured prompt, calls Ollama at `temperature=0.1`
3. **Zero-shot layer** — complex queries (ranking, top-N, percentages); calls Ollama at `temperature=0.2` with schema-only prompt

The classifier triggers zero-shot on keywords like `排名`, `top`, `前`, `最高`, `最低`, `占比`, `百分比`. Everything else defaults to few-shot.

### Few-shot Example Library

`data/few_shot_examples.json` — 120 examples, each with fields: `query`, `sql`, `keywords`, `category`, `difficulty`. Retrieval is keyword intersection scoring (70% weight on `keywords` field match, 30% on query text match). No embeddings or vector search.

### Schema Cognition (DWD/DWS Detection)

`schema_service.py::detect_layer()` applies three methods in order:
1. Query `table_metadata` table if present in the DB
2. Check for `dws_` / `dwd_` naming prefix
3. Keyword heuristics (`summary`, `daily`, `agg`, etc. → DWS)

`analyze_domain()` similarly maps table names to 7 business domains (订单域, 客户域, 产品域, 员工域, 供应商域, 物流域, 其他).

### Frontend (`frontend/src/`)

Single-page app with two top-level views toggled by `mainTab` in `Text2SQLPage.jsx`:
- **SQL查询** — datasource selector → optional table picker → natural language input → SQL display → results/optimize/analyze tabs
- **数据库结构** — `DatabaseCognition.jsx` showing DWD/DWS layers, domains, AI table recommendations; supports one-click jump to SQL查询 with pre-selected tables

The `ResultsTable.jsx` auto-renders a bar chart only when the result has exactly 2 columns and the second column is entirely numeric (deliberate conservative rule — local 7B model can't reliably judge chart type).

API calls all go through `frontend/src/services/api.js` (axios, base URL `http://localhost:8000/api`).

### Key Configuration

`backend/config.py` (via `backend/.env`):
- `OLLAMA_MODEL` — default `qwen2.5-coder:7b`
- `DEMO_DB_PATH` — resolves to `../data/demo_ecommerce.db`
- `FEW_SHOT_PATH` — resolves to `../data/few_shot_examples.json`
- `AUTO_MODE_MAX_TABLES` / `AUTO_MODE_MAX_COLUMNS` — thresholds for auto/smart/manual query mode

### Pydantic v2 Compatibility

`text2sql_routes.py` contains a `convert_schema_to_dict()` helper that manually converts Pydantic model lists to dicts before passing them to service layer functions. This is required because service functions accept plain `List[Dict]`, not Pydantic models. When adding new routes that pass schema through, always call this converter.

## Demo Databases

| File | Contents |
|---|---|
| `data/demo_ecommerce.db` | E-commerce orders (default demo target) |
| `data/northwind.db` | Northwind data warehouse — 16 tables, DWD/DWS layers, 7 business domains |
| `backend/data/Chinook_Sqlite_*.sqlite` | Music store sample DB |
