"""
Query Cache Service - 查询缓存与频次统计
将 (查询文本 + 数据源ID) → 生成的SQL 持久化到 app.db，
并记录命中次数，为后续优化分析提供数据支撑。
"""

import hashlib
import sqlite3
from typing import Optional, Dict, List
from pathlib import Path

_APP_DB_PATH = Path(__file__).parent.parent / "data" / "app.db"

_DDL = """
CREATE TABLE IF NOT EXISTS query_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key    TEXT    UNIQUE NOT NULL,
    query_text   TEXT    NOT NULL,
    datasource_id TEXT,
    generated_sql TEXT   NOT NULL,
    strategy     TEXT,
    hit_count    INTEGER DEFAULT 0,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cache_key ON query_cache(cache_key);
CREATE INDEX IF NOT EXISTS idx_hit_count  ON query_cache(hit_count DESC);
"""


def _make_key(query: str, datasource_id: Optional[str]) -> str:
    raw = f"{query.strip().lower()}|{datasource_id or ''}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_APP_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


class QueryCacheService:
    """查询缓存服务（单例）"""

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        try:
            conn = _get_conn()
            conn.executescript(_DDL)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ 查询缓存表初始化失败: {e}")

    def get(self, query: str, datasource_id: Optional[str]) -> Optional[Dict]:
        """从缓存查找，命中则更新统计并返回，否则返回 None"""
        key = _make_key(query, datasource_id)
        try:
            conn = _get_conn()
            row = conn.execute(
                "SELECT generated_sql, strategy, hit_count FROM query_cache WHERE cache_key = ?",
                (key,)
            ).fetchone()

            if row:
                conn.execute(
                    "UPDATE query_cache SET hit_count = hit_count + 1, last_used_at = CURRENT_TIMESTAMP WHERE cache_key = ?",
                    (key,)
                )
                conn.commit()
                conn.close()
                return {
                    "sql": row["generated_sql"],
                    "strategy": row["strategy"],
                    "hit_count": row["hit_count"] + 1,
                    "from_cache": True,
                }
            conn.close()
        except Exception as e:
            print(f"⚠️ 缓存读取失败: {e}")
        return None

    def set(self, query: str, datasource_id: Optional[str], sql: str, strategy: str = None):
        """写入缓存（已存在则忽略，不覆盖）"""
        key = _make_key(query, datasource_id)
        try:
            conn = _get_conn()
            conn.execute(
                """INSERT OR IGNORE INTO query_cache
                   (cache_key, query_text, datasource_id, generated_sql, strategy)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, query.strip(), datasource_id, sql, strategy)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ 缓存写入失败: {e}")

    def get_stats(self, limit: int = 20) -> Dict:
        """返回缓存统计：总量、热门查询 Top N"""
        try:
            conn = _get_conn()
            total = conn.execute("SELECT COUNT(*) FROM query_cache").fetchone()[0]
            top = conn.execute(
                "SELECT query_text, datasource_id, hit_count, strategy, last_used_at "
                "FROM query_cache ORDER BY hit_count DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
            return {
                "total_cached": total,
                "top_queries": [dict(r) for r in top]
            }
        except Exception as e:
            return {"total_cached": 0, "top_queries": [], "error": str(e)}

    def clear(self, datasource_id: Optional[str] = None) -> int:
        """清空缓存，可按数据源过滤，返回删除行数"""
        try:
            conn = _get_conn()
            if datasource_id:
                cur = conn.execute(
                    "DELETE FROM query_cache WHERE datasource_id = ?", (datasource_id,)
                )
            else:
                cur = conn.execute("DELETE FROM query_cache")
            count = cur.rowcount
            conn.commit()
            conn.close()
            return count
        except Exception as e:
            print(f"⚠️ 缓存清除失败: {e}")
            return 0


_cache_service: Optional[QueryCacheService] = None


def get_cache_service() -> QueryCacheService:
    global _cache_service
    if _cache_service is None:
        _cache_service = QueryCacheService()
    return _cache_service
