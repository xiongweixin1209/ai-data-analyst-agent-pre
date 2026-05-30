"""
数据源相关的Pydantic Schemas
定义API请求和响应的数据结构
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


# ============ 请求模型 ============

class DataSourceCreate(BaseModel):
    """添加数据源的请求模型"""

    name: str = Field(..., min_length=1, max_length=100, description="数据源名称")
    type: str = Field(default="sqlite", description="数据库类型：sqlite/mysql/postgresql")

    # SQLite专用
    file_path: Optional[str] = Field(None, description="SQLite文件路径")

    # MySQL/PostgreSQL专用
    host: Optional[str] = Field(None, max_length=100, description="数据库主机地址")
    port: Optional[int] = Field(None, ge=1, le=65535, description="端口号")
    database: Optional[str] = Field(None, max_length=100, description="数据库名")
    username: Optional[str] = Field(None, max_length=100, description="用户名")
    password: Optional[str] = Field(None, max_length=200, description="密码")

    is_default: bool = Field(default=False, description="是否设为默认数据源")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Demo电商数据库",
                "type": "sqlite",
                "file_path": "data/demo_ecommerce.db",
                "is_default": True
            }
        }
    )


class DataSourceUpdate(BaseModel):
    """更新数据源的请求模型"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "更新后的名称",
                "is_default": True
            }
        }
    )


# ============ 响应模型 ============

class DataSourceResponse(BaseModel):
    """数据源响应模型（返回给前端）"""

    id: int
    name: str
    type: str
    file_path: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    # 注意：不返回密码！
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)  # 允许从ORM模型转换


class DataSourceListResponse(BaseModel):
    """数据源列表响应"""

    total: int = Field(..., description="总数量")
    items: list[DataSourceResponse] = Field(..., description="数据源列表")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total": 2,
                "items": [
                    {
                        "id": 1,
                        "name": "Demo电商数据库",
                        "type": "sqlite",
                        "file_path": "demo_ecommerce.db",
                        "is_default": True,
                        "is_active": True
                    }
                ]
            }
        }
    )


# ============ 通用响应模型 ============

class MessageResponse(BaseModel):
    """通用消息响应"""

    message: str = Field(..., description="响应消息")
    success: bool = Field(default=True, description="是否成功")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "操作成功",
                "success": True
            }
        }
    )