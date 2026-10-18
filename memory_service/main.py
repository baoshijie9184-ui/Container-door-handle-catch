"""
mem0 记忆服务 - 基于 FastAPI + mem0 + Chroma
为智能助手提供用户长期记忆能力
"""

import os
import sys
import logging
import hashlib
import hmac
import json
import threading
from pathlib import Path
from typing import Any, Optional, Literal
from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv
try:
    from .write_receipts import MemoryWriter, ReceiptError
except ImportError:  # Docker / start_server.py load main as a top-level module.
    from write_receipts import MemoryWriter, ReceiptError

# 加载 .env 文件
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

# 优先加载指定的本地 Mem0 源码仓库，便于与项目内的服务封装联调。
mem0_source_path = os.getenv("MEM0_SOURCE_PATH")
if mem0_source_path and mem0_source_path not in sys.path:
    sys.path.insert(0, mem0_source_path)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PrivateMemoryLogFilter(logging.Filter):
    """原生 Mem0 会在 INFO 和异常中输出正文，桥接层只保留级别。"""
    def filter(self, record):
        record.msg = "Mem0 internal operation (%s)"
        record.args = (record.levelname,)
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


logging.getLogger("mem0.memory.main").addFilter(PrivateMemoryLogFilter())

# mem0 实例（延迟初始化）
memory_instance = None
# 当前本地桥接使用单进程；将人工更新、删除和自动提炼串行化。
memory_write_lock = threading.Lock()
memory_writer = None


@contextmanager
def memory_write_slot():
    # Do not park every FastAPI worker behind a long extraction, which would block reads again.
    if not memory_write_lock.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="Memory write busy; operation not started", headers={"Retry-After": "2"})
    try:
        yield
    finally:
        memory_write_lock.release()


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
    llm_model = os.getenv("MEM0_LLM_MODEL") or os.getenv("DASHSCOPE_MODEL", "kimi-k3")
    embedding_api_key = required_env("EMBEDDING_API_KEY")
    embedding_base_url = os.getenv("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    embedding_model = os.getenv("EMBEDDING_MODEL", "qwen3.7-text-embedding-flash")

    config = {
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
    # 服务器可将整个目录挂载为持久卷；未配置时保留本机既有路径。
    data_dir = os.getenv("MEM0_DATA_DIR")
    if data_dir:
        storage = Path(data_dir).expanduser().resolve()
        storage.mkdir(parents=True, exist_ok=True)
        config["vector_store"]["config"]["path"] = str(storage / "chroma")
        config["history_db_path"] = str(storage / "history.db")
    return config


def bounded_setting(name, default, minimum, maximum):
    value = float(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError("Invalid memory service timing configuration")
    return value


def configure_provider_timeouts(memory):
    # The pinned Mem0 constructor does not forward a timeout to its OpenAI clients.
    timeout = bounded_setting("MEM0_PROVIDER_TIMEOUT_SECONDS", 15, 0.1, 120)
    for provider in (memory.llm, memory.embedding_model):
        provider.client = provider.client.with_options(timeout=timeout, max_retries=0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global memory_instance, memory_writer
    logger.info("正在初始化 mem0 记忆服务...")
    writer = None
    try:
        directory = Path(os.getenv("MEM0_DATA_DIR") or Path(__file__).parent / "bridge_state") / "bridge_receipts"
        writer = MemoryWriter(directory, lambda: memory_instance, memory_write_lock,
                                     response_wait=bounded_setting("MEM0_WRITE_RESPONSE_SECONDS", 3, 0.01, 4),
                                     operation_seconds=bounded_setting("MEM0_WRITE_REVIEW_SECONDS", 120, 1, 1800))
        from mem0 import Memory
        config = get_memory_config()
        memory_instance = Memory.from_config(config)
        configure_provider_timeouts(memory_instance)
        memory_writer = writer
        logger.info("mem0 记忆服务初始化完成")
    except Exception as e:
        if writer is not None:
            writer.close(wait=False)
        logger.error("mem0 初始化失败: %s", type(e).__name__)
        raise

    try:
        yield
    finally:
        writer.close(wait=False)
        if memory_writer is writer:
            memory_writer = None
        logger.info("mem0 记忆服务关闭")


app = FastAPI(
    title="DoorHandleCatch 记忆服务",
    description="基于 mem0 的用户长期记忆服务",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def authenticate_memory_bridge(request: Request, call_next):
    if request.url.path.startswith("/memories"):
        token = os.getenv("MEM0_BRIDGE_TOKEN", "")
        if not token:
            return JSONResponse(status_code=503, content={"detail": "Memory bridge authentication is not configured"})
        if not hmac.compare_digest(request.headers.get("x-doorhandle-memory-token", "").encode("utf-8"), token.encode("utf-8")):
            return JSONResponse(status_code=401, content={"detail": "Memory bridge authentication required"})
    return await call_next(request)


class OwnedMemoryListRequest(BaseModel):
    user_id: str = Field(..., pattern=r"^doorhandlecatch:user:[1-9][0-9]*$")
    app_id: Literal["doorhandlecatch"]
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=2147483546)


class OwnedMemoryGetRequest(BaseModel):
    user_id: str = Field(..., pattern=r"^doorhandlecatch:user:[1-9][0-9]*$")
    app_id: Literal["doorhandlecatch"]
    memory_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class OwnedMemoryDeleteRequest(OwnedMemoryGetRequest):
    expected_digest: str = Field(..., pattern=r"^[a-f0-9]{64}$")


class OwnedMemoryUpdateRequest(OwnedMemoryDeleteRequest):
    memory: str = Field(..., min_length=1, max_length=4000)

    @field_validator("memory")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Memory text cannot be blank")
        return value.strip()


def memory_digest(item: dict) -> str:
    version = {key: item.get(key) for key in ("id", "memory", "user_id", "agent_id", "run_id", "updated_at")}
    return hashlib.sha256(json.dumps(version, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def public_memory_item(row: dict) -> dict:
    return {"id": row["id"], "memory": row.get("memory", ""), "sourceSessionId": row.get("run_id"),
            "createdAt": row.get("created_at"), "updatedAt": row.get("updated_at"), "digest": memory_digest(row)}


@app.post("/memories/owned/get")
def get_owned_memory(request: OwnedMemoryGetRequest):
    try:
        current = get_owned_record(request)
        return {"code": 200, "data": public_memory_item(current)}
    except HTTPException:
        raise
    except Exception:
        logger.warning("Owned memory reading failed")
        raise HTTPException(status_code=503, detail="Memory storage is unavailable")


@app.post("/memories/owned/list")
def list_owned_memories(request: OwnedMemoryListRequest):
    try:
        # Mem0 2.0.19 get_all 只有 top_k。使用当前 Chroma 的原生分页，避免每页全量扫描。
        collection = memory_instance.vector_store.collection
        result = collection.get(where={"$and": [{"user_id": {"$eq": request.user_id}}, {"agent_id": {"$eq": request.app_id}}]},
                                limit=request.limit + 1, offset=request.offset, include=["metadatas"])
        ids, metadata = result.get("ids", []), result.get("metadatas", [])
        if len(ids) != len(metadata):
            raise ValueError("Invalid memory page")
        items = []
        for id, payload in zip(ids[:request.limit], metadata[:request.limit]):
            # 再次校验范围，正文始终使用白名单转换，不泄露原始 metadata。
            if payload and payload.get("user_id") == request.user_id and payload.get("agent_id") == request.app_id:
                row = {key: payload.get(key) for key in ("user_id", "agent_id", "run_id", "created_at", "updated_at")}
                row.update(id=id, memory=payload.get("data", ""))
                items.append(public_memory_item(row))
        has_more = len(ids) > request.limit
        return {"code": 200, "data": {"items": items, "hasMore": has_more, "nextOffset": request.offset + request.limit if has_more else None}}
    except Exception:
        logger.warning("Owned memory listing failed")
        raise HTTPException(status_code=503, detail="Memory storage is unavailable")


@app.post("/memories/owned/delete")
def delete_owned_memory(request: OwnedMemoryDeleteRequest):
    try:
        with memory_write_slot():
            check_owned_version(request)
            memory_instance.delete(request.memory_id)
        return {"code": 200, "data": {"deleted": True}}
    except HTTPException:
        raise
    except Exception:
        logger.warning("Owned memory deletion outcome is unknown")
        raise HTTPException(status_code=503, detail="Deletion outcome needs verification")


def get_owned_record(request: OwnedMemoryGetRequest) -> dict:
    current = memory_instance.get(request.memory_id)
    if not current or current.get("user_id") != request.user_id or current.get("agent_id") != request.app_id:
        raise HTTPException(status_code=404, detail="Memory is unavailable")
    return current


def check_owned_version(request: OwnedMemoryDeleteRequest) -> dict:
    current = get_owned_record(request)
    if not hmac.compare_digest(memory_digest(current), request.expected_digest):
        raise HTTPException(status_code=409, detail="Memory changed; refresh before changing")
    return current


@app.post("/memories/owned/update")
def update_owned_memory(request: OwnedMemoryUpdateRequest):
    try:
        with memory_write_slot():
            check_owned_version(request)
            # 原生 update 会重算向量，保持检索正文和索引一致，不调用提炼 LLM。
            memory_instance.update(request.memory_id, text=request.memory)
        return {"code": 200, "data": {"updated": True}}
    except HTTPException:
        raise
    except Exception:
        logger.warning("Owned memory update outcome is unknown")
        raise HTTPException(status_code=503, detail="Update outcome needs verification")


# ==================== 数据模型 ====================

class AddMemoryRequest(BaseModel):
    """添加记忆请求"""
    user_id: str = Field(..., pattern=r"^doorhandlecatch:user:[1-9][0-9]*$", max_length=80)
    app_id: Literal["doorhandlecatch"]
    run_id: str = Field(..., min_length=1, max_length=128, description="会话ID")
    content: str = Field(..., min_length=1, max_length=64000, description="记忆内容")
    request_id: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    metadata: Optional[dict] = Field(None, description="元数据")

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value):
        if value is not None and (set(value) - {"source", "timestamp", "turn_id"}
                                  or any(not isinstance(item, (str, int, float, bool)) for item in value.values())
                                  or len(json.dumps(value, ensure_ascii=False)) > 2000):
            raise ValueError("Memory metadata is unsupported")
        return value


class SearchMemoryRequest(BaseModel):
    """搜索记忆请求"""
    user_id: str = Field(..., pattern=r"^doorhandlecatch:user:[1-9][0-9]*$", max_length=80)
    app_id: Literal["doorhandlecatch"]
    run_id: str = Field(..., min_length=1, description="会话ID")
    query: str = Field(..., description="搜索查询")
    top_k: int = Field(5, ge=1, le=20, description="返回数量")
    scope: Literal["SESSION", "ACCOUNT"] = "SESSION"


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
    return {"status": "ok", "service": "memory", "memory_scopes": ["SESSION", "ACCOUNT"], "governance": True, "owned_edit": True, "owned_pagination": True, "write_receipts": memory_writer is not None, "bridge_auth_configured": bool(os.getenv("MEM0_BRIDGE_TOKEN"))}


@app.post("/memories/add", response_model=ApiResponse)
def add_memory(request: AddMemoryRequest):
    """添加记忆"""
    try:
        if memory_writer is None:
            raise HTTPException(503, "Memory receipt storage is unavailable; operation not started", headers={"X-Memory-Operation-Started": "false"})
        result = memory_writer.submit(request.user_id, request.app_id, request.run_id, request.content, request.metadata, request.request_id)
        if result["status"] == "SUCCEEDED":
            return ApiResponse(data={"results": result["results"], "operation": result})
        if result["status"] == "RUNNING":
            return JSONResponse(status_code=202, content={"code": 202, "message": "Memory extraction is running", "data": {"operation": result}})
        return JSONResponse(status_code=409, content={"code": 409, "message": "Memory outcome needs verification; not replayed", "data": {"operation": result}})
    except ReceiptError as error:
        headers = {"Retry-After": "2"} if error.status == 503 else {}
        if error.not_started:
            headers["X-Memory-Operation-Started"] = "false"
        raise HTTPException(error.status, error.detail, headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("添加记忆结果待核对: %s", type(e).__name__)
        raise HTTPException(status_code=503, detail="Memory write outcome needs verification")


class MemoryOperationRequest(BaseModel):
    user_id: str = Field(..., pattern=r"^doorhandlecatch:user:[1-9][0-9]*$", max_length=80)
    app_id: Literal["doorhandlecatch"]
    request_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


@app.post("/memories/operations/get", response_model=ApiResponse)
def memory_operation(request: MemoryOperationRequest):
    if memory_writer is None:
        raise HTTPException(503, "Memory receipt storage is unavailable")
    try:
        return ApiResponse(data=memory_writer.receipt(request.user_id, request.app_id, request.request_id))
    except ReceiptError as error:
        raise HTTPException(error.status, error.detail)
    except Exception:
        raise HTTPException(503, "Memory receipt storage is unavailable")


@app.post("/memories/search", response_model=ApiResponse)
def search_memories(request: SearchMemoryRequest):
    """搜索记忆"""
    try:
        filters = {"user_id": request.user_id, "agent_id": request.app_id}
        if request.scope == "SESSION":
            filters["run_id"] = request.run_id
        results = memory_instance.search(
            request.query,
            filters=filters,
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
        logger.warning("搜索记忆暂不可用: %s", type(e).__name__)
        raise HTTPException(status_code=503, detail="Memory search is unavailable")


@app.get("/memories/{user_id}")
@app.delete("/memories/{memory_id}")
@app.delete("/memories/user/{user_id}")
async def retired_unscoped_operation(user_id: str = "", memory_id: str = ""):
    raise HTTPException(status_code=410, detail="Use authenticated account-scoped memory operations")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8081)
