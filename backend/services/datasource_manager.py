"""
Datasource Manager - 数据源管理服务
功能：数据源连接管理、Schema获取、执行器创建
修复：自动从app.db加载数据源，解决内存缓存和数据库不同步的问题
"""

import sqlite3
import time
from typing import Dict, List, Optional
from pathlib import Path

# 兼容两种导入方式
try:
    from .sql_executor import SQLExecutor
except ImportError:
    from sql_executor import SQLExecutor


_APP_DB_PATH = Path(__file__).parent.parent / "data" / "app.db"
_SCHEMA_CACHE_TTL = 300  # schema 缓存有效期（秒）


class DatasourceManager:
    """数据源管理器"""

    def __init__(self):
        self._executors: Dict[str, SQLExecutor] = {}
        self._datasources: Dict[str, Dict] = {}
        self._schema_cache: Dict[str, Dict] = {}
        self._schema_cache_ts: Dict[str, float] = {}

        # 启动时从数据库加载所有数据源
        self._load_all_from_db()

    def _load_all_from_db(self):
        """启动时从app.db加载所有数据源到内存"""
        try:
            if not _APP_DB_PATH.exists():
                print(f"⚠️ app.db不存在: {_APP_DB_PATH}")
                return

            conn = sqlite3.connect(str(_APP_DB_PATH))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, file_path, type FROM datasources")
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                ds_id = str(row["id"])
                self._datasources[ds_id] = {
                    "id": ds_id,
                    "db_path": row["file_path"],
                    "name": row["name"],
                    "description": "",
                    "type": row["type"] if row["type"] else "sqlite"
                }

            print(f"✅ 从数据库加载了 {len(rows)} 个数据源")
            for ds in self._datasources.values():
                print(f"   - ID: {ds['id']}, 名称: {ds['name']}, 路径: {ds['db_path']}")

        except Exception as e:
            print(f"⚠️ 从数据库加载数据源失败: {e}")

    def _load_single_from_db(self, datasource_id: str) -> bool:
        """从app.db加载单个数据源（按需加载）"""
        try:
            if not _APP_DB_PATH.exists():
                return False

            conn = sqlite3.connect(str(_APP_DB_PATH))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, file_path, type FROM datasources WHERE id = ?",
                (datasource_id,)
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                self._datasources[datasource_id] = {
                    "id": datasource_id,
                    "db_path": row["file_path"],
                    "name": row["name"],
                    "description": "",
                    "type": row["type"] if row["type"] else "sqlite"
                }
                return True

            return False

        except Exception as e:
            print(f"⚠️ 从数据库加载数据源 {datasource_id} 失败: {e}")
            return False

    def register_datasource(
            self,
            datasource_id: str,
            db_path: str,
            name: str = None,
            description: str = None
    ) -> bool:
        """注册数据源"""
        try:
            if not Path(db_path).exists():
                raise FileNotFoundError(f"数据库文件不存在: {db_path}")

            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.close()

            self._datasources[datasource_id] = {
                "id": datasource_id,
                "db_path": db_path,
                "name": name or f"datasource_{datasource_id}",
                "description": description or "",
                "type": "sqlite"
            }

            return True

        except Exception as e:
            print(f"注册数据源失败: {e}")
            return False

    def get_executor(self, datasource_id: str) -> Optional[SQLExecutor]:
        """获取数据源的执行器"""
        # 内存中找不到？尝试从数据库加载
        if datasource_id not in self._datasources:
            if not self._load_single_from_db(datasource_id):
                print(f"数据源不存在: {datasource_id}")
                return None

        # 检查缓存
        if datasource_id in self._executors:
            return self._executors[datasource_id]

        # 创建新执行器
        try:
            db_path = self._datasources[datasource_id]["db_path"]
            executor = SQLExecutor(db_path)
            self._executors[datasource_id] = executor
            return executor

        except Exception as e:
            print(f"创建执行器失败: {e}")
            return None

    def get_schema(self, datasource_id: str) -> Dict:
        """获取数据源的 Schema（带 TTL 内存缓存）"""
        # 命中有效缓存直接返回
        now = time.monotonic()
        if datasource_id in self._schema_cache:
            if now - self._schema_cache_ts.get(datasource_id, 0) < _SCHEMA_CACHE_TTL:
                return self._schema_cache[datasource_id]

        executor = self.get_executor(datasource_id)
        if not executor:
            return {"success": False, "tables": [], "error": "无法连接到数据源"}

        try:
            conn_test = executor.test_connection()
            if not conn_test["success"]:
                return {"success": False, "tables": [], "error": conn_test["message"]}

            tables = []
            for table_name in conn_test["tables"]:
                table_info = executor.get_table_info(table_name)
                if table_info["success"]:
                    tables.append({
                        "table_name": table_name,
                        "columns": table_info["columns"],
                        "row_count": table_info["row_count"]
                    })

            schema = {"success": True, "tables": tables, "error": None}
            self._schema_cache[datasource_id] = schema
            self._schema_cache_ts[datasource_id] = now
            return schema

        except Exception as e:
            return {"success": False, "tables": [], "error": str(e)}

    def invalidate_schema_cache(self, datasource_id: str):
        """主动失效某个数据源的 schema 缓存"""
        self._schema_cache.pop(datasource_id, None)
        self._schema_cache_ts.pop(datasource_id, None)

    def list_datasources(self) -> List[Dict]:
        """列出所有数据源"""
        return list(self._datasources.values())

    def get_datasource_info(self, datasource_id: str) -> Optional[Dict]:
        """获取数据源信息"""
        # 内存中找不到？尝试从数据库加载
        if datasource_id not in self._datasources:
            self._load_single_from_db(datasource_id)

        return self._datasources.get(datasource_id)

    def remove_datasource(self, datasource_id: str) -> bool:
        """移除数据源并清除关联缓存"""
        if datasource_id in self._datasources:
            self._executors.pop(datasource_id, None)
            del self._datasources[datasource_id]
            self.invalidate_schema_cache(datasource_id)
            return True
        return False


# 全局单例
_datasource_manager = None


def get_datasource_manager() -> DatasourceManager:
    """获取数据源管理器单例"""
    global _datasource_manager
    if _datasource_manager is None:
        _datasource_manager = DatasourceManager()
    return _datasource_manager
