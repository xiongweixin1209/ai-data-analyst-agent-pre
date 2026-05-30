"""
Datasource Manager - 数据源管理服务
功能：
- 数据源连接管理、Schema 获取、执行器创建
- 启动时从 app.db 加载已注册数据源
- 启动时自动扫描 data/ 与 EXTERNAL_DATA_DIRS,把发现的 db 文件自动注册
- 启动时检测"幽灵数据源"(file_path 不存在),温和警告不删
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

try:
    from ..config import settings
except ImportError:
    from config import settings


_APP_DB_PATH = Path(__file__).parent.parent / "data" / "app.db"
# 项目根目录下的 data/(放业务/示例数据库),自动扫描默认目录
_LOCAL_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_SCHEMA_CACHE_TTL = 300  # schema 缓存有效期（秒）
_AUTO_SCAN_EXTS = ("*.db", "*.sqlite", "*.sqlite3")


class DatasourceManager:
    """数据源管理器"""

    def __init__(self):
        self._executors: Dict[str, SQLExecutor] = {}
        self._datasources: Dict[str, Dict] = {}
        self._schema_cache: Dict[str, Dict] = {}
        self._schema_cache_ts: Dict[str, float] = {}

        # 启动时:1) 从 app.db 加载已注册;2) 扫盘自动注册新文件;3) 检测幽灵记录
        self._load_all_from_db()
        self._auto_register_from_disk()
        self._check_ghost_records()

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

    # ------------------------------------------------------------------ #
    # 启动时自动扫描注册 + 幽灵记录检测
    # ------------------------------------------------------------------ #

    def _scan_directories(self) -> List[Path]:
        """返回所有需要扫描的目录:本地 data/ + EXTERNAL_DATA_DIRS"""
        dirs: List[Path] = []
        if _LOCAL_DATA_DIR.exists() and _LOCAL_DATA_DIR.is_dir():
            dirs.append(_LOCAL_DATA_DIR)
        for d in (settings.EXTERNAL_DATA_DIRS or []):
            p = Path(d)
            if p.exists() and p.is_dir():
                dirs.append(p)
            else:
                print(f"⚠️ EXTERNAL_DATA_DIRS 配置项不存在或不是目录,跳过: {d}")
        return dirs

    def _auto_register_from_disk(self):
        """扫描各数据目录,把未注册的 .db / .sqlite / .sqlite3 文件自动注册成数据源。

        幂等:已注册的文件会被跳过,不会重复 INSERT。
        去重依据:file_path 解析为绝对路径后作为唯一键(避免相对/绝对路径误判)。
        """
        if not _APP_DB_PATH.exists():
            print(f"⚠️ 自动扫描跳过:app.db 不存在 ({_APP_DB_PATH})")
            return
        try:
            conn = sqlite3.connect(str(_APP_DB_PATH))
            cur = conn.cursor()

            # 1. 收集已注册的 file_path 集合(归一化为 resolve 后的绝对路径)
            cur.execute(
                "SELECT file_path FROM datasources WHERE type='sqlite' AND file_path IS NOT NULL"
            )
            registered: set = set()
            for (fp,) in cur.fetchall():
                if fp:
                    try:
                        registered.add(str(Path(fp).resolve()))
                    except Exception:
                        pass  # 路径无效就忽略

            # 2. 遍历目录、文件,新文件 INSERT
            new_count = 0
            for scan_dir in self._scan_directories():
                for ext in _AUTO_SCAN_EXTS:
                    for db_file in scan_dir.glob(ext):
                        # 跳过 app.db 自己(它是应用元数据,不是业务数据源)
                        if db_file.name == "app.db":
                            continue
                        abs_path = str(db_file.resolve())
                        if abs_path in registered:
                            continue
                        name = db_file.stem  # 文件名去后缀作为默认名称
                        cur.execute(
                            """INSERT INTO datasources
                               (name, type, file_path, is_default, is_active)
                               VALUES (?, 'sqlite', ?, 0, 1)""",
                            (name, str(db_file))
                        )
                        new_id = cur.lastrowid
                        registered.add(abs_path)
                        new_count += 1
                        # 同步到内存
                        self._datasources[str(new_id)] = {
                            "id": str(new_id),
                            "db_path": str(db_file),
                            "name": name,
                            "description": "",
                            "type": "sqlite",
                        }
                        print(f"   + 自动注册: id={new_id}, name='{name}', path={db_file}")

            conn.commit()
            conn.close()
            if new_count > 0:
                print(f"✅ 自动扫描注册完成,新增 {new_count} 个数据源")
            else:
                print(f"ℹ️ 自动扫描完成:无新文件需要注册")
        except Exception as e:
            print(f"⚠️ 自动扫描注册失败: {e}")

    def _check_ghost_records(self):
        """检测并警告 file_path 指向的文件已不存在的"幽灵数据源",但不删除。

        策略说明:温和警告而不自动删除,原因是文件可能临时不在(硬盘移走、
        路径暂时错误等),自动删除会导致数据源配置永久丢失。用户可在 UI 里
        手动清理这些幽灵记录。
        """
        ghosts = []
        for ds_id, ds in self._datasources.items():
            path = ds.get("db_path")
            if not path:
                continue
            if not Path(path).exists():
                ghosts.append((ds_id, ds.get("name", "?"), path))

        if ghosts:
            print(f"⚠️ 检测到 {len(ghosts)} 个幽灵数据源(文件不存在,记录保留供恢复):")
            for ds_id, name, path in ghosts:
                print(f"   - ID={ds_id}, name='{name}', path={path}")
            print(f"   提示:如需清理,可在前端 UI 删除对应数据源")
        else:
            print(f"✅ 所有 {len(self._datasources)} 个数据源 file_path 均有效")

    # ------------------------------------------------------------------ #
    # 原有 API
    # ------------------------------------------------------------------ #

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
