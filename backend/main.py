"""
智汇研途 - AI科研辅助平台 后端服务
提供 DeepSeek API 调用接口与 RAG 文献检索接口。

运行方式（在 backend/ 目录下执行）：
    uvicorn main:app --reload
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os
import time
import hashlib
import requests

# 加载环境变量（无论从哪个目录启动，都定位到 backend/.env）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

app = FastAPI(title="智汇研途 API", version="1.0.0", docs_url=None)

# 允许跨域，前端页面可直接调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


# ==================== 自定义 /docs（改用国内 CDN，避免 jsdelivr 被墙导致页面空白） ====================
_SWAGGER_JS = "https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.0.0/swagger-ui-bundle.min.js"
_SWAGGER_CSS = "https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.0.0/swagger-ui.min.css"


@app.get("/docs", include_in_schema=False)
def custom_docs():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url=_SWAGGER_JS,
        swagger_css_url=_SWAGGER_CSS,
    )


# ==================== 请求/响应模型 ====================
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户提出的研究问题")
    temperature: float = Field(0.7, ge=0.0, le=1.0, description="采样温度")


class ChatResponse(BaseModel):
    answer: str
    model: str
    usage: dict | None = None


# ==================== DeepSeek API 调用（带超时重试） ====================
def call_deepseek(question: str, temperature: float, retries: int = 2) -> dict:
    """调用 DeepSeek Chat API，失败时按指数退避重试。"""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="未配置 DEEPSEEK_API_KEY，请在 backend/.env 中填写后重启服务",
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEFAULT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "你是一名严谨的科研助手，擅长文献综述、学术思路梳理与实验设计，回答时请给出结构化、可核验的结论。",
            },
            {"role": "user", "content": question},
        ],
        "temperature": temperature,
    }

    last_err = "未知错误"
    for attempt in range(retries + 1):
        try:
            resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "answer": data["choices"][0]["message"]["content"],
                    "model": data.get("model", DEFAULT_MODEL),
                    "usage": data.get("usage"),
                }
            # 限流/服务端错误可重试
            if resp.status_code in (429, 500, 502, 503) and attempt < retries:
                last_err = f"HTTP {resp.status_code}"
                time.sleep(2 ** attempt)
                continue
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        except requests.exceptions.Timeout:
            last_err = "请求超时"
        except requests.exceptions.RequestException as e:
            last_err = str(e)
        if attempt < retries:
            time.sleep(2 ** attempt)

    raise HTTPException(status_code=502, detail=f"DeepSeek API 调用失败：{last_err}")


# ==================== 基础路由 ====================
@app.get("/health")
def health():
    return {"status": "ok", "model": DEFAULT_MODEL}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """真实 DeepSeek 对话接口。"""
    return call_deepseek(request.question, request.temperature)


# ==================== RAG 文献检索（ChromaDB 向量库） ====================
# 使用确定性哈希嵌入，无需外部 Embedding 模型即可离线演示向量检索流程，
# 可替换为真实 Embedding（如 DeepSeek/OpenAI 嵌入接口）以获得更好效果。
try:
    import chromadb  # noqa: E402
except ImportError:  # 未安装 chromadb 时 RAG 接口降级，不影响 /api/chat 正常对话
    chromadb = None

_chroma_client = None
_collection = None


def _hash_embed(text: str, dim: int = 256) -> list[float]:
    """基于字符 n-gram 哈希的确定性嵌入（演示用）。"""
    vec = [0.0] * dim
    tokens = [text[i : i + 3] for i in range(max(1, len(text) - 2))]
    if not tokens:
        tokens = [text]
    for tk in tokens:
        h = int(hashlib.md5(tk.encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = max(1.0, sum(v * v for v in vec) ** 0.5)
    return [v / norm for v in vec]


def _get_collection():
    global _chroma_client, _collection
    if chromadb is None:
        raise HTTPException(
            status_code=501,
            detail="未安装 chromadb，RAG 接口不可用；请执行 pip install chromadb 后重启服务",
        )
    if _collection is None:
        try:
            _chroma_client = chromadb.PersistentClient(path="./chroma_data")
            _collection = _chroma_client.get_or_create_collection(name="literature")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"ChromaDB 初始化失败：{e}")
    return _collection


class IngestRequest(BaseModel):
    text: str
    doc_id: str | None = None
    metadata: dict | None = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(3, ge=1, le=10)


@app.post("/api/rag/ingest")
def rag_ingest(req: IngestRequest):
    """写入一篇文献片段到向量库。"""
    col = _get_collection()
    doc_id = req.doc_id or hashlib.md5(req.text.encode("utf-8")).hexdigest()[:16]
    kwargs = {
        "ids": [doc_id],
        "documents": [req.text],
        "embeddings": [_hash_embed(req.text)],
    }
    if req.metadata:  # chromadb 1.x 要求 metadata 非空，未传时不带该参数
        kwargs["metadatas"] = [req.metadata]
    col.upsert(**kwargs)
    return {"ok": True, "doc_id": doc_id}


@app.post("/api/rag/search")
def rag_search(req: SearchRequest):
    """按语义相似度检索相关文献片段。"""
    col = _get_collection()
    result = col.query(query_embeddings=[_hash_embed(req.query)], n_results=req.top_k)
    docs = result.get("documents", [[]])[0]
    return {"results": docs}
