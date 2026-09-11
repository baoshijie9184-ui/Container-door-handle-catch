"""
mem0 记忆服务 - 基于 FastAPI + mem0 + Chroma
为智能助手提供用户长期记忆能力
"""

import os
import sys
import logging
from typing import Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv("../.env", override=True)

# 优先加载指定的本地 Mem0 源码仓库，便于与项目内的服务封装联调。
mem0_source_path = os.getenv("MEM0_SOURCE_PATH")
if mem0_source_path and mem0_source_path not in sys.path:
    sys.path.insert(0, mem0_source_path)

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
    llm_api_key = required_env("DASHSCOPE_API_KEY")
    llm_base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    llm_model = os.getenv("AGENTSCOPE_AI_MODEL", "dashscope:kimi-k3").split(":")[-1]
    embedding_api_key = required_env("EMBEDDING_API_KEY")
    embedding_base_url = os.getenv("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    embedding_model = os.getenv("EMBEDDING_MODEL", "qwen3.7-text-embedding-flash")

    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": llm_model,
                "api_key": llm_api_key,
                "openai_base_url": llm_base_url,
                "is_reasoning_model": True,
            }
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": embedding_model,
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
            agent_id=request.app_id,
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
            filters={
                "user_id": request.user_id,
                "agent_id": request.app_id,
                "run_id": request.run_id,
            },
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
