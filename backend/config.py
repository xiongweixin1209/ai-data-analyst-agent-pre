"""
应用配置管理
"""

from typing import List
from pydantic_settings import BaseSettings
from pathlib import Path

# 注:应用元数据库(datasources / query_cache / field_comments)的位置
# 由 database.py 直接定位到 backend/data/app.db,无需在此重复声明。
# 之前 config.py 里的 DATABASE_URL 字段实际从未被任何代码引用,已删除。


class Settings(BaseSettings):
    """应用配置"""

    # 应用配置
    APP_NAME: str = "Text-to-SQL API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    API_PORT: int = 8000

    # Ollama配置
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5-coder:7b"
    OLLAMA_TIMEOUT: int = 60  # 超时时间（秒）

    # Demo数据库路径
    DEMO_DB_PATH: str = str(Path(__file__).parent.parent / "data" / "demo_ecommerce.db")

    # Few-shot示例路径
    FEW_SHOT_PATH: str = str(Path(__file__).parent.parent / "data" / "few_shot_examples.json")

    # 数据源自动扫描的外部目录
    # 启动时 datasource_manager 会扫描 backend/../data/ + 这里配置的每个目录,
    # 把发现的 .db / .sqlite 文件自动注册成数据源(已注册则跳过)。
    # 用于 Plan C 等外部数据仓库对接:配上数据仓库路径,文件落进去就自动可见。
    EXTERNAL_DATA_DIRS: List[str] = []

    # SQL配置
    SQL_TIMEOUT: int = 30  # SQL执行超时（秒）
    MAX_RESULT_ROWS: int = 1000  # 最大返回行数

    # 查询模式判断阈值
    AUTO_MODE_MAX_TABLES: int = 10  # 自动全量模式的表数量上限
    AUTO_MODE_MAX_COLUMNS: int = 100  # 自动全量模式的字段数量上限

    class Config:
        env_file = ".env"
        case_sensitive = True
        # 容忍 .env 里出现 Settings 没声明的字段(如历史遗留的 DATABASE_URL),
        # 否则 pydantic-settings v2 会因 "Extra inputs are not permitted" 启动失败
        extra = "ignore"

# 创建全局配置实例
settings = Settings()