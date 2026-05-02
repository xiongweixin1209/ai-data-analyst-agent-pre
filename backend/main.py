"""
Text-to-SQL Backend API
FastAPI应用入口 - CORS修复版 + Text2SQL完整集成
"""

import sys
import io

# Windows GBK终端下强制UTF-8输出，防止emoji/中文字符报UnicodeEncodeError
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from database import init_db
from config import settings
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 全局变量：Text-to-SQL可用性标识
text2sql_available = False
text2sql_import_error = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    print("=" * 60)
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 正在启动...")
    print("=" * 60)

    # 初始化数据库
    init_db()
    print(f"✅ 数据库初始化完成")

    # 配置信息
    print(f"\n📊 配置信息:")
    print(f"   - Demo数据库: {settings.DEMO_DB_PATH}")
    print(f"   - Few-shot示例: {settings.FEW_SHOT_PATH}")
    print(f"   - Ollama模型: {settings.OLLAMA_MODEL}")

    # API端点
    print(f"\n📚 API端点:")
    print(f"   - API文档: http://localhost:{settings.API_PORT}/docs")
    print(f"   - 健康检查: http://localhost:{settings.API_PORT}/health")
    print(f"   - 数据源管理: http://localhost:{settings.API_PORT}/api/datasource")

    if text2sql_available:
        print(f"   - Text-to-SQL生成: http://localhost:{settings.API_PORT}/api/text2sql/generate")
        print(f"   - Text-to-SQL执行: http://localhost:{settings.API_PORT}/api/text2sql/execute")
        print(f"   - SQL优化分析: http://localhost:{settings.API_PORT}/api/text2sql/optimize")
        print(f"   - 性能分析: http://localhost:{settings.API_PORT}/api/text2sql/analyze")
    else:
        print(f"   ⚠️ Text-to-SQL功能未启用")
        if text2sql_import_error:
            print(f"      原因: {text2sql_import_error}")

    print("=" * 60)
    print(f"✅ 服务启动完成！")
    print("=" * 60)

    yield

    print("\n" + "=" * 60)
    print("👋 Text-to-SQL API 正在关闭...")
    print("=" * 60)


# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    description="基于本地LLM的自然语言转SQL工具",
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# ============================================================
# CORS配置 - 必须在所有路由之前！
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 全局OPTIONS处理器 - 确保预检请求成功
# ============================================================
@app.middleware("http")
async def add_cors_header(request: Request, call_next):
    """添加CORS头部"""
    if request.method == "OPTIONS":
        return JSONResponse(
            content={"message": "OK"},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
            }
        )

    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


# ============================================================
# 基础路由
# ============================================================
@app.get("/")
def read_root():
    """根路径"""
    return {
        "message": "Text-to-SQL API 服务运行中",
        "status": "ok",
        "version": settings.APP_VERSION,
        "text2sql_enabled": text2sql_available
    }


@app.get("/health")
def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "text2sql_enabled": text2sql_available,
        "endpoints": {
            "datasource": True,
            "schema": True,
            "text2sql": text2sql_available
        }
    }


# ============================================================
# 注册路由
# ============================================================

# 1. 数据源和Schema路由（必需）
try:
    from api import datasource as datasource_api
    from api import schema as schema_api

    app.include_router(datasource_api.router)
    app.include_router(schema_api.router)
    print("✅ 数据源和Schema路由已注册")
except ImportError as e:
    print(f"❌ 数据源路由导入失败: {e}")
    raise

# 2. Text-to-SQL路由（可选，但强烈建议）
try:
    from api.text2sql_routes import router as text2sql_router
    app.include_router(text2sql_router)
    text2sql_available = True
    print("✅ Text-to-SQL路由已注册")
    print(f"   - 路由前缀: {text2sql_router.prefix}")
    print(f"   - 包含端点: generate, execute, optimize, analyze")
except ImportError as e:
    text2sql_available = False
    text2sql_import_error = str(e)
    print(f"⚠️ Text-to-SQL路由导入失败: {e}")
    print(f"   提示: Text-to-SQL功能将不可用，但数据源管理功能正常")
except Exception as e:
    text2sql_available = False
    text2sql_import_error = str(e)
    print(f"❌ Text-to-SQL路由注册失败: {e}")


# ============================================================
# 调试端点（仅开发环境）
# ============================================================
@app.get("/debug/routes")
def list_routes():
    """列出所有注册的路由（调试用）"""
    routes = []
    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            routes.append({
                "path": route.path,
                "methods": list(route.methods) if route.methods else [],
                "name": route.name
            })
    return {
        "total": len(routes),
        "routes": routes
    }


# ============================================================
# 启动服务
# ============================================================
if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 60)
    print("🔧 启动配置:")
    print(f"   - 主机: 0.0.0.0")
    print(f"   - 端口: {settings.API_PORT}")
    print(f"   - 重载: True")
    print(f"   - 日志级别: info")
    print("=" * 60 + "\n")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.API_PORT,
        log_level="info",
        reload=True
    )