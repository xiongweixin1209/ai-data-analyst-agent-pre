"""
Field Comment Service - LLM 自动生成字段业务注释
首次访问数据源时调用 Ollama 推断每张表/字段的中文业务含义，
结果持久化到 app.db，后续直接读缓存，零等待。
"""

import json
import sqlite3
import re
from typing import Dict, List, Optional
from pathlib import Path

_APP_DB_PATH = Path(__file__).parent.parent / "data" / "app.db"

_DDL = """
CREATE TABLE IF NOT EXISTS field_comments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    datasource_id  TEXT    NOT NULL,
    table_name     TEXT    NOT NULL,
    column_name    TEXT,
    comment        TEXT    NOT NULL,
    generated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(datasource_id, table_name, column_name)
);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_APP_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


class FieldCommentService:
    """字段注释服务（单例）"""

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        try:
            conn = _get_conn()
            conn.executescript(_DDL)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ 字段注释表初始化失败: {e}")

    # ------------------------------------------------------------------ #
    # 读取缓存
    # ------------------------------------------------------------------ #

    def get_comments_for_datasource(self, datasource_id: str) -> Dict[str, Dict]:
        """
        返回该数据源已缓存的所有注释，格式：
        {
          "table_name": {
              "__table__": "表级注释",
              "col_a": "字段注释",
              ...
          }
        }
        """
        result: Dict[str, Dict] = {}
        try:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT table_name, column_name, comment FROM field_comments WHERE datasource_id = ?",
                (datasource_id,)
            ).fetchall()
            conn.close()
            for row in rows:
                tbl = row["table_name"]
                col = row["column_name"] or "__table__"
                result.setdefault(tbl, {})[col] = row["comment"]
        except Exception as e:
            print(f"⚠️ 读取字段注释失败: {e}")
        return result

    def has_comments(self, datasource_id: str, table_name: str) -> bool:
        """判断某张表是否已生成过注释"""
        try:
            conn = _get_conn()
            count = conn.execute(
                "SELECT COUNT(*) FROM field_comments WHERE datasource_id = ? AND table_name = ?",
                (datasource_id, table_name)
            ).fetchone()[0]
            conn.close()
            return count > 0
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # 写入缓存
    # ------------------------------------------------------------------ #

    def _save_comments(self, datasource_id: str, table_name: str, comment_map: Dict):
        """将 LLM 返回的注释字典写入 DB"""
        try:
            conn = _get_conn()
            table_comment = comment_map.get("table_comment", "")
            if table_comment:
                conn.execute(
                    "INSERT OR REPLACE INTO field_comments (datasource_id, table_name, column_name, comment) VALUES (?, ?, NULL, ?)",
                    (datasource_id, table_name, table_comment)
                )
            for col, cmt in comment_map.get("columns", {}).items():
                conn.execute(
                    "INSERT OR REPLACE INTO field_comments (datasource_id, table_name, column_name, comment) VALUES (?, ?, ?, ?)",
                    (datasource_id, table_name, col, cmt)
                )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ 保存字段注释失败: {e}")

    # ------------------------------------------------------------------ #
    # LLM 推断
    # ------------------------------------------------------------------ #

    def generate_for_table(
        self,
        datasource_id: str,
        table_name: str,
        columns: List[Dict],
        llm_service
    ) -> Dict:
        """
        若该表尚无注释，调用 LLM 生成后缓存并返回。
        llm_service: LLMService 实例
        返回 {column_name: comment, "__table__": table_comment}
        """
        if self.has_comments(datasource_id, table_name):
            cached = self.get_comments_for_datasource(datasource_id)
            return cached.get(table_name, {})

        col_names = [c.get("name", "") for c in columns]
        prompt = f"""你是数据库业务专家。根据表名和字段名，用简洁的中文（5-15字）描述其业务含义。

表名：{table_name}
字段列表：{', '.join(col_names)}

请严格按如下JSON格式输出，不要输出其他任何内容：
{{
  "table_comment": "该表的业务描述",
  "columns": {{
    {', '.join(f'"{c}": "字段含义"' for c in col_names[:5])}
  }}
}}"""

        try:
            result = llm_service.generate(prompt=prompt, temperature=0.1, max_tokens=600)
            if not result.get("success"):
                return {}

            raw = result.get("sql") or result.get("raw_response") or ""
            # 提取 JSON（LLM 有时会在代码块里输出）
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if not json_match:
                return {}

            comment_map = json.loads(json_match.group())
            self._save_comments(datasource_id, table_name, comment_map)
            return {
                "__table__": comment_map.get("table_comment", ""),
                **comment_map.get("columns", {})
            }
        except Exception as e:
            print(f"⚠️ 生成字段注释失败 [{table_name}]: {e}")
            return {}

    def generate_for_schema(
        self,
        datasource_id: str,
        schema: List[Dict],
        llm_service
    ) -> Dict[str, Dict]:
        """
        为整个 schema（多张表）批量生成注释，已有缓存的表跳过。
        返回 {table_name: {col: comment}}
        """
        all_comments = self.get_comments_for_datasource(datasource_id)
        for table in schema:
            tbl = table.get("table_name", "")
            if not self.has_comments(datasource_id, tbl):
                comments = self.generate_for_table(
                    datasource_id, tbl, table.get("columns", []), llm_service
                )
                if comments:
                    all_comments[tbl] = comments
        return all_comments


_comment_service: Optional[FieldCommentService] = None


def get_comment_service() -> FieldCommentService:
    global _comment_service
    if _comment_service is None:
        _comment_service = FieldCommentService()
    return _comment_service
