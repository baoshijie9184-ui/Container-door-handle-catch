"""
mem0 记忆服务 - 基于 FastAPI + mem0 + Chroma
为智能助手提供用户长期记忆能力
"""

import os
import logging
from typing import Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv("../.env")

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# mem0 实例（延迟初始化）
memory_instance = None


def required_env(name: str) -> str:
    """读取必需环境变量，避免把 API Key 写进源码。"""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_memory_config():
    """构建 mem0 配置"""
    from mem0.configs.base import MemoryConfig
    from mem0.configs.vector_stores.chroma import ChromaDbConfig
    from mem0.configs.llms.deepseek import DeepSeekConfig

    # DeepSeek 配置
    deepseek_api_key = required_env("DEEPSEEK_API_KEY")
    deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    embedding_api_key = required_env("EMBEDDING_API_KEY")
    embedding_base_url = os.getenv("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    return {
        "llm": {
            "provider": "deepseek",
            "config": {
                "model": "deepseek-v4-flash",
                "api_key": deepseek_api_key,
                "deepseek_base_url": deepseek_base_url,
                "temperature": 0.1,
            }
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "text-embedding-v4",
                "api_key": embedding_api_key,
                "openai_base_url": embedding_base_url
            }
        },
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": "doorhandle_memories",
                "path": os.path.join(os.path.dirname(__file__), "chroma_db")
            }
        }
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global memory_instance
    logger.info("正在初始化 mem0 记忆服务...")

    try:
        from mem0 import Memory
        config = get_memory_config()
        memory_instance = Memory.from_config(config)
        logger.info("mem0 记忆服务初始化完成")
    except Exception as e:
        logger.error(f"mem0 初始化失败: {e}")
        raise

    yield

    logger.info("mem0 记忆服务关闭")


app = FastAPI(
    title="DoorHandleCatch 记忆服务",
    description="基于 mem0 的用户长期记忆服务",
    version="1.0.0",
    lifespan=lifespan,
)


# ==================== 数据模型 ====================

class AddMemoryRequest(BaseModel):
    """添加记忆请求"""
    user_id: str = Field(..., description="用户ID")
    app_id: str = Field(..., min_length=1, description="应用ID")
    run_id: str = Field(..., min_length=1, description="会话ID")
    content: str = Field(..., description="记忆内容")
    metadata: Optional[dict] = Field(None, description="元数据")


class SearchMemoryRequest(BaseModel):
    """搜索记忆请求"""
    user_id: str = Field(..., description="用户ID")
    app_id: str = Field(..., min_length=1, description="应用ID")
    run_id: str = Field(..., min_length=1, description="会话ID")
    query: str = Field(..., description="搜索查询")
    top_k: int = Field(5, description="返回数量")


class MemoryResponse(BaseModel):
    """记忆响应"""
    id: str
    memory: str
    metadata: Optional[dict] = None
    score: Optional[float] = None


class ApiResponse(BaseModel):
    """统一 API 响应"""
    code: int = 200
    message: str = "success"
    data: Optional[Any] = None


# ==================== API 接口 ====================

@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "memory"}


@app.post("/memories/add", response_model=ApiResponse)
async def add_memory(request: AddMemoryRequest):
    """添加记忆"""
    try:
        result = memory_instance.add(
            request.content,
            user_id=request.user_id,
            app_id=request.app_id,
            run_id=request.run_id,
            metadata=request.metadata,
        )
        logger.info(f"添加记忆成功: user={request.user_id}, content={request.content[:50]}...")
        return ApiResponse(data=result)
    except Exception as e:
        logger.error(f"添加记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/memories/search", response_model=ApiResponse)
async def search_memories(request: SearchMemoryRequest):
    """搜索记忆"""
    try:
        results = memory_instance.search(
            request.query,
            filters={"AND": [
                {"user_id": request.user_id},
                {"app_id": request.app_id},
                {"run_id": request.run_id},
            ]},
            top_k=request.top_k,
        )
        memories = []
        for item in (results.get("results") or []):
            memories.append(MemoryResponse(
                id=item.get("id", ""),
                memory=item.get("memory", ""),
                metadata=item.get("metadata"),
                score=item.get("score"),
            ))
        return ApiResponse(data=memories)
    except Exception as e:
        logger.error(f"搜索记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memories/{user_id}", response_model=ApiResponse)
async def get_all_memories(user_id: str, top_k: int = 100):
    """获取用户所有记忆"""
    try:
        results = memory_instance.get_all(
            filters={"user_id": user_id},
            top_k=top_k,
        )
        memories = []
        for item in (results.get("results") or []):
            memories.append(MemoryResponse(
                id=item.get("id", ""),
                memory=item.get("memory", ""),
                metadata=item.get("metadata"),
            ))
        return ApiResponse(data=memories)
    except Exception as e:
        logger.error(f"获取记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memories/{memory_id}", response_model=ApiResponse)
async def delete_memory(memory_id: str):
    """删除单条记忆"""
    try:
        memory_instance.delete(memory_id)
        return ApiResponse(message="记忆已删除")
    except Exception as e:
        logger.error(f"删除记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memories/user/{user_id}", response_model=ApiResponse)
async def delete_all_user_memories(user_id: str):
    """删除用户所有记忆"""
    try:
        memory_instance.delete_all(user_id=user_id)
        return ApiResponse(message="用户所有记忆已删除")
    except Exception as e:
        logger.error(f"删除用户记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
