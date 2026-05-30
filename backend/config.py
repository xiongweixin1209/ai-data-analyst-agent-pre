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
    #
    # 默认值指向跟 text-to-sql 同级的 data-warehouse/pharma 目录,这是跟
    # 上游 drug-data-pipeline 项目的"数据契约"位置 —— pipeline 把清洗后的
    # 药品销售数据集发布到这里,TTS 启动自动扫描并注册成数据源。
    # 这是 publish-consume 模式,两个项目代码层零耦合,只通过文件交换衔接。
    #
    # 可用 EXTERNAL_DATA_DIRS 环境变量覆盖(逗号分隔多个路径)。
    EXTERNAL_DATA_DIRS: List[str] = [
        str(Path(__file__).parent.parent.parent / "data-warehouse" / "pharma"),
    ]

    # RAG (Hybrid embedding + jieba) 检索开关
    # 默认 False = 纯 jieba 字面匹配,这是 eval 验证过 EX 最高的配置(97.5%)。
    # True = 启用 Hybrid RAG,带来同义词/口语化匹配能力,但牺牲 ~4s/query
    # 延迟,且在 few-shot 库精心调优的场景下 EX 微降(-3.7%,落在单次 eval
    # 噪声窗内)。建议仅在面对 OOD 查询(用户用了示例库没有的同义词)时启用。
    #
    # 启用方式:环境变量 ENABLE_RAG=true,或直接改这个默认值。
    ENABLE_RAG: bool = False

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