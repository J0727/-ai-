"""
智汇研途 - AI科研辅助平台 后端服务
提供 DeepSeek API 调用接口与 RAG 文献检索接口。

运行方式（在 backend/ 目录下执行）：
    uvicorn main:app --reload
"""
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os
import io
import re
import time
import hashlib
import secrets
import sqlite3
from datetime import datetime
import requests
from pypdf import PdfReader

# 加载环境变量（无论从哪个目录启动，都定位到 backend/.env）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ==================== 用户数据库（SQLite 持久化） ====================
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.db")


def _init_user_db():
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "username TEXT UNIQUE NOT NULL, "
        "password_hash TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "last_login TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "username TEXT NOT NULL, "
        "subject_id TEXT NOT NULL, "
        "subject_name TEXT NOT NULL, "
        "item_title TEXT, "
        "item_url TEXT, "
        "note TEXT, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS teams ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name TEXT NOT NULL, "
        "code TEXT UNIQUE NOT NULL, "
        "owner TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS team_members ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "team_id INTEGER NOT NULL, "
        "username TEXT NOT NULL, "
        "role TEXT NOT NULL, "
        "joined_at TEXT NOT NULL, "
        "UNIQUE(team_id, username))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS team_docs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "team_id INTEGER NOT NULL, "
        "title TEXT NOT NULL, "
        "content TEXT DEFAULT '', "
        "updated_by TEXT, "
        "updated_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()


_init_user_db()

# ==================== 学科资料库分类（两级：学科 → 细分领域） ====================
_SUBJECTS = [
    {"id": "cs", "name": "计算机科学", "keyword": "computer science", "children": [
        {"id": "cs-ai", "name": "人工智能", "keyword": "artificial intelligence"},
        {"id": "cs-software", "name": "软件工程", "keyword": "software engineering"},
        {"id": "cs-hardware", "name": "计算机硬件", "keyword": "computer hardware architecture"},
        {"id": "cs-network", "name": "计算机网络", "keyword": "computer networks"},
        {"id": "cs-db", "name": "数据库", "keyword": "database systems"},
        {"id": "cs-security", "name": "信息安全", "keyword": "cybersecurity"},
        {"id": "cs-cv", "name": "计算机视觉", "keyword": "computer vision"},
        {"id": "cs-nlp", "name": "自然语言处理", "keyword": "natural language processing"},
        {"id": "cs-algo", "name": "算法与理论", "keyword": "algorithms theory"},
        {"id": "cs-hci", "name": "人机交互", "keyword": "human computer interaction"},
    ]},
    {"id": "ai", "name": "人工智能", "keyword": "artificial intelligence", "children": [
        {"id": "ai-ml", "name": "机器学习", "keyword": "machine learning"},
        {"id": "ai-dl", "name": "深度学习", "keyword": "deep learning"},
        {"id": "ai-rl", "name": "强化学习", "keyword": "reinforcement learning"},
        {"id": "ai-llm", "name": "大语言模型", "keyword": "large language model"},
        {"id": "ai-mm", "name": "多模态", "keyword": "multimodal learning"},
        {"id": "ai-kg", "name": "知识图谱", "keyword": "knowledge graph"},
        {"id": "ai-agent", "name": "智能体", "keyword": "autonomous agent"},
        {"id": "ai-xai", "name": "可解释AI", "keyword": "explainable artificial intelligence"},
    ]},
    {"id": "med", "name": "临床医学", "keyword": "clinical medicine", "children": [
        {"id": "med-internal", "name": "内科学", "keyword": "internal medicine"},
        {"id": "med-surgery", "name": "外科学", "keyword": "surgery"},
        {"id": "med-pediatrics", "name": "儿科学", "keyword": "pediatrics"},
        {"id": "med-obgyn", "name": "妇产科学", "keyword": "obstetrics gynecology"},
        {"id": "med-oncology", "name": "肿瘤学", "keyword": "oncology"},
        {"id": "med-neuro", "name": "神经病学", "keyword": "neurology"},
        {"id": "med-imaging", "name": "影像医学", "keyword": "medical imaging"},
        {"id": "med-public", "name": "公共卫生", "keyword": "public health"},
    ]},
    {"id": "bio", "name": "生物学", "keyword": "molecular biology", "children": [
        {"id": "bio-mol", "name": "分子生物学", "keyword": "molecular biology"},
        {"id": "bio-cell", "name": "细胞生物学", "keyword": "cell biology"},
        {"id": "bio-genetics", "name": "遗传学", "keyword": "genetics"},
        {"id": "bio-eco", "name": "生态学", "keyword": "ecology"},
        {"id": "bio-neuro", "name": "神经科学", "keyword": "neuroscience"},
        {"id": "bio-immuno", "name": "免疫学", "keyword": "immunology"},
        {"id": "bio-bioinfo", "name": "生物信息学", "keyword": "bioinformatics"},
    ]},
    {"id": "phys", "name": "物理学", "keyword": "quantum physics", "children": [
        {"id": "phys-quantum", "name": "量子物理", "keyword": "quantum physics"},
        {"id": "phys-condensed", "name": "凝聚态物理", "keyword": "condensed matter physics"},
        {"id": "phys-particle", "name": "粒子物理", "keyword": "particle physics"},
        {"id": "phys-optics", "name": "光学", "keyword": "optics"},
        {"id": "phys-astro", "name": "天体物理", "keyword": "astrophysics"},
        {"id": "phys-plasma", "name": "等离子体物理", "keyword": "plasma physics"},
        {"id": "phys-stat", "name": "统计物理", "keyword": "statistical physics"},
    ]},
    {"id": "chem", "name": "化学", "keyword": "organic chemistry", "children": [
        {"id": "chem-organic", "name": "有机化学", "keyword": "organic chemistry"},
        {"id": "chem-inorganic", "name": "无机化学", "keyword": "inorganic chemistry"},
        {"id": "chem-physical", "name": "物理化学", "keyword": "physical chemistry"},
        {"id": "chem-analytical", "name": "分析化学", "keyword": "analytical chemistry"},
        {"id": "chem-polymer", "name": "高分子化学", "keyword": "polymer chemistry"},
        {"id": "chem-electro", "name": "电化学", "keyword": "electrochemistry"},
        {"id": "chem-catalysis", "name": "催化化学", "keyword": "catalysis"},
    ]},
    {"id": "math", "name": "数学", "keyword": "mathematics", "children": [
        {"id": "math-algebra", "name": "代数", "keyword": "algebra"},
        {"id": "math-geometry", "name": "几何", "keyword": "geometry"},
        {"id": "math-analysis", "name": "分析", "keyword": "mathematical analysis"},
        {"id": "math-probability", "name": "概率统计", "keyword": "probability statistics"},
        {"id": "math-numerical", "name": "数值计算", "keyword": "numerical analysis"},
        {"id": "math-topology", "name": "拓扑学", "keyword": "topology"},
        {"id": "math-differential", "name": "微分方程", "keyword": "differential equations"},
        {"id": "math-numbertheory", "name": "数论", "keyword": "number theory"},
    ]},
    {"id": "econ", "name": "经济学", "keyword": "economics", "children": [
        {"id": "econ-micro", "name": "微观经济", "keyword": "microeconomics"},
        {"id": "econ-macro", "name": "宏观经济", "keyword": "macroeconomics"},
        {"id": "econ-econometrics", "name": "计量经济", "keyword": "econometrics"},
        {"id": "econ-finance", "name": "金融学", "keyword": "finance"},
        {"id": "econ-trade", "name": "国际贸易", "keyword": "international trade"},
        {"id": "econ-development", "name": "发展经济", "keyword": "development economics"},
        {"id": "econ-behavioral", "name": "行为经济", "keyword": "behavioral economics"},
    ]},
    {"id": "law", "name": "法学", "keyword": "law", "children": [
        {"id": "law-civil", "name": "民法", "keyword": "civil law"},
        {"id": "law-criminal", "name": "刑法", "keyword": "criminal law"},
        {"id": "law-constitutional", "name": "宪法", "keyword": "constitutional law"},
        {"id": "law-administrative", "name": "行政法", "keyword": "administrative law"},
        {"id": "law-international", "name": "国际法", "keyword": "international law"},
        {"id": "law-commercial", "name": "商法", "keyword": "commercial law"},
        {"id": "law-ip", "name": "知识产权", "keyword": "intellectual property"},
        {"id": "law-environmental", "name": "环境法", "keyword": "environmental law"},
    ]},
    {"id": "edu", "name": "教育学", "keyword": "education", "children": [
        {"id": "edu-higher", "name": "高等教育", "keyword": "higher education"},
        {"id": "edu-basic", "name": "基础教育", "keyword": "basic education"},
        {"id": "edu-psychology", "name": "教育心理", "keyword": "educational psychology"},
        {"id": "edu-technology", "name": "教育技术", "keyword": "educational technology"},
        {"id": "edu-curriculum", "name": "课程论", "keyword": "curriculum design"},
        {"id": "edu-teacher", "name": "教师教育", "keyword": "teacher education"},
        {"id": "edu-vocational", "name": "职业教育", "keyword": "vocational education"},
    ]},
    {"id": "eng", "name": "工程技术", "keyword": "engineering", "children": [
        {"id": "eng-mechanical", "name": "机械工程", "keyword": "mechanical engineering"},
        {"id": "eng-electronic", "name": "电子工程", "keyword": "electronic engineering"},
        {"id": "eng-civil", "name": "土木工程", "keyword": "civil engineering"},
        {"id": "eng-chemical", "name": "化学工程", "keyword": "chemical engineering"},
        {"id": "eng-materials", "name": "材料科学", "keyword": "materials science"},
        {"id": "eng-energy", "name": "能源工程", "keyword": "energy engineering"},
        {"id": "eng-aerospace", "name": "航空航天", "keyword": "aerospace engineering"},
        {"id": "eng-automation", "name": "自动化", "keyword": "automation control"},
    ]},
    {"id": "psych", "name": "心理学", "keyword": "psychology", "children": [
        {"id": "psych-cognitive", "name": "认知心理", "keyword": "cognitive psychology"},
        {"id": "psych-developmental", "name": "发展心理", "keyword": "developmental psychology"},
        {"id": "psych-social", "name": "社会心理", "keyword": "social psychology"},
        {"id": "psych-clinical", "name": "临床心理", "keyword": "clinical psychology"},
        {"id": "psych-neuro", "name": "神经心理", "keyword": "neuropsychology"},
        {"id": "psych-industrial", "name": "工业心理", "keyword": "industrial psychology"},
        {"id": "psych-measurement", "name": "心理测量", "keyword": "psychometrics"},
    ]},
]


def _find_subject(sid: str):
    """在两级学科树中查找，返回 (学科, 子领域或 None)。"""
    for s in _SUBJECTS:
        if s["id"] == sid:
            return s, None
        for c in s.get("children", []):
            if c["id"] == sid:
                return s, c
    return None, None

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
    sources: list[dict] | None = None


# ==================== DeepSeek API 调用（带超时重试） ====================
def _build_system_prompt(context: str = "") -> str:
    base = "你是一名严谨的科研助手，擅长文献综述、学术思路梳理与实验设计，回答时请给出结构化、可核验的结论。"
    if context:
        base += (
            "\n\n【检索到的文献片段】\n" + context
            + "\n\n请优先依据以上文献片段作答，并在回答中注明依据；若片段不足以回答，请明确说明。"
        )
    return base


def call_deepseek(question: str, temperature: float, context: str = "", retries: int = 2) -> dict:
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
            {"role": "system", "content": _build_system_prompt(context)},
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
    """真实 DeepSeek 对话接口（若向量库中有文献，会自动带上检索到的上下文与来源）。"""
    context, sources = _retrieve_context(request.question, 3)
    result = call_deepseek(request.question, request.temperature, context)
    result["sources"] = sources or None
    return result


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


def _cosine(a, b) -> float:
    """余弦相似度。"""
    s = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return s / (na * nb) if na and nb else 0.0


def _retrieve_context(topic: str, k: int = 3):
    """从向量库检索与主题相关的片段，返回 (context, sources)。"""
    if chromadb is None:
        return "", []
    try:
        col = _get_collection()
        res = col.query(query_embeddings=[_hash_embed(topic)], n_results=k)
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        context = "\n\n".join(d for d in docs if d)
        sources = []
        for d, m in zip(docs, metas):
            if d:
                meta = m or {}
                sources.append({
                    "snippet": d[:120],
                    "source": meta.get("source", "上传文献"),
                    "chunk": meta.get("chunk"),
                })
        return context, sources
    except Exception:
        return "", []


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


# ==================== PDF 上传与解析 ====================
class UploadResponse(BaseModel):
    ok: bool
    filename: str
    num_pages: int
    num_chunks: int


def chunk_text(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    """把长文本切成带重叠的片段，便于向量检索。"""
    text = " ".join(text.split())
    if not text:
        return []
    step = max(1, size - overlap)
    chunks = []
    for i in range(0, len(text), step):
        chunk = text[i:i + size]
        if chunk:
            chunks.append(chunk)
        if i + size >= len(text):
            break
    return chunks


def _ocr_pdf(content: bytes) -> str:
    """对扫描件 PDF 逐页渲染并 OCR（RapidOCR + PyMuPDF）。"""
    import pymupdf as fitz  # pymupdf 2.0+ 推荐写法
    import cv2
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR

    ocr = RapidOCR()
    doc = fitz.open(stream=content, filetype="pdf")
    parts = []
    for page in doc:
        pix = page.get_pixmap(dpi=150, alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        result, _ = ocr(bgr)
        if result:
            parts.append("".join(r[1] for r in result))
    return "\n".join(parts)


@app.post("/api/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...)):
    """上传 PDF 文献：提取文本 → 切片 → 写入向量库，供后续问答检索。"""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只支持 PDF 文件")
    content = await file.read()
    try:
        reader = PdfReader(io.BytesIO(content))
        num_pages = len(reader.pages)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF 解析失败：{e}")
    if not text.strip():
        # 扫描件 PDF：回退到 OCR
        try:
            text = _ocr_pdf(content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"扫描件 OCR 失败：{e}")
    if not text.strip():
        raise HTTPException(status_code=400, detail="未提取到任何文本（含 OCR 后仍为空）")
    chunks = chunk_text(text)
    col = _get_collection()
    for i, ch in enumerate(chunks):
        col.upsert(
            ids=[f"{file.filename}#{i}"],
            documents=[ch],
            embeddings=[_hash_embed(ch)],
            metadatas=[{"source": file.filename, "chunk": i}],
        )
    return UploadResponse(ok=True, filename=file.filename, num_pages=num_pages, num_chunks=len(chunks))


# ==================== 写作辅助：论文大纲生成 ====================
class WritingRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="论文/课题主题")


class WritingResponse(BaseModel):
    outline: str
    model: str
    sources: list[dict] | None = None


@app.post("/api/writing", response_model=WritingResponse)
def writing_assistant(req: WritingRequest):
    """基于已上传文献，为指定主题生成学术论文大纲（含真实来源）。"""
    context, sources = _retrieve_context(req.topic, 5)
    prompt = (
        f"请围绕主题「{req.topic}」撰写一份学术论文大纲，包含以下部分："
        "摘要要点、引言要点、相关工作、方法、实验设计、预期结论。"
        "请用 Markdown 标题层级呈现，若提供了文献片段请优先依据它们。"
    )
    result = call_deepseek(prompt, 0.7, context)
    return WritingResponse(outline=result["answer"], model=result["model"], sources=sources or None)


# ==================== 引用图谱与综述生成 ====================
class GraphResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    hub: str | None = None


@app.get("/api/graph", response_model=GraphResponse)
def build_graph(threshold: float = 0.25, max_nodes: int = 30):
    """基于已入库文献片段构建相似度引用图谱，并挖掘「基石节点」（度数最高）。"""
    col = _get_collection()
    data = col.get(include=["documents", "metadatas", "embeddings"])

    def _take(key):
        v = data.get(key)
        return list(v)[:max_nodes] if v is not None else []

    ids = _take("ids")
    docs = _take("documents")
    metas = _take("metadatas")
    embs = _take("embeddings")

    nodes = []
    for i, doc_id in enumerate(ids):
        meta = metas[i] or {}
        nodes.append({
            "id": doc_id,
            "label": f"{meta.get('source', '文献')}#{meta.get('chunk', '')}",
            "snippet": (docs[i] or "")[:80],
        })

    edges = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            sim = float(_cosine(embs[i], embs[j]))
            if sim >= threshold:
                edges.append({"source": ids[i], "target": ids[j], "weight": round(sim, 3)})

    degree = {n["id"]: 0 for n in nodes}
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1
    hub = max(degree, key=degree.get) if degree else None
    return GraphResponse(nodes=nodes, edges=edges, hub=hub)


@app.post("/api/survey", response_model=WritingResponse)
def generate_survey(req: WritingRequest):
    """基于已入库文献生成领域综述（研究背景/方法流派/关键发现/挑战与未来）。"""
    context, sources = _retrieve_context(req.topic, 6)
    prompt = (
        f"请围绕「{req.topic}」撰写一份领域文献综述，包含：研究背景、主要方法与流派、"
        "关键发现、现存挑战与未来方向。请用 Markdown 呈现，并优先依据提供的文献片段。"
    )
    result = call_deepseek(prompt, 0.7, context)
    return WritingResponse(outline=result["answer"], model=result["model"], sources=sources or None)


# ==================== 学术翻译（多语言） ====================
_LANGUAGES = {
    "en": "英语", "zh": "中文", "ja": "日语", "ko": "韩语",
    "es": "西班牙语", "fr": "法语", "de": "德语", "ru": "俄语",
    "ar": "阿拉伯语", "pt": "葡萄牙语", "it": "意大利语", "th": "泰语",
    "vi": "越南语", "hi": "印地语", "id": "印尼语", "tr": "土耳其语",
    "nl": "荷兰语", "pl": "波兰语", "uk": "乌克兰语", "sv": "瑞典语",
}


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, description="待翻译文本")
    target: str = Field("en", description="目标语言代码：en/zh/ja/ko/es/fr/de/ru/ar/pt 等")


class TranslateResponse(BaseModel):
    translated: str
    model: str
    target_name: str = ""


@app.get("/api/languages")
def list_languages():
    """返回支持的目标语言列表。"""
    return {"languages": [{"code": k, "name": v} for k, v in _LANGUAGES.items()]}


@app.post("/api/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest):
    """多语言学术互译，保留专业术语与代码。"""
    code = (req.target or "en").lower()
    target_name = _LANGUAGES.get(code, "英语")
    prompt = f"请将以下学术文本翻译为{target_name}，保留专业术语、公式与代码不译：\n\n{req.text}"
    result = call_deepseek(prompt, 0.3, "")
    return TranslateResponse(translated=result["answer"], model=result["model"], target_name=target_name)


# ==================== 界面全页翻译（批量） ====================
class BatchTranslateRequest(BaseModel):
    texts: list[str] = Field(..., description="待翻译的界面文本列表")
    target: str = Field("en", description="目标语言代码")


class BatchTranslateResponse(BaseModel):
    translations: list[str]
    model: str


@app.post("/api/translate-batch", response_model=BatchTranslateResponse)
def translate_batch(req: BatchTranslateRequest):
    """批量翻译界面文本，返回与输入等长、同顺序的译文列表。"""
    if not req.texts:
        return BatchTranslateResponse(translations=[], model=DEFAULT_MODEL)
    code = (req.target or "en").lower()
    target_name = _LANGUAGES.get(code, "英语")
    import json as _json

    prompt = (
        f"请把下面 JSON 数组中的每个字符串翻译为{target_name}，保持数组长度和顺序完全不变。"
        "只翻译自然语言，不翻译专有名词/缩写（如 CSV、arXiv、LaTeX、PDF、DeepSeek、RAG、Transformer、GitHub、API）。"
        "必须返回与输入等长的 JSON 字符串数组，不要任何额外解释、不要 Markdown 代码块。\n\n"
        + _json.dumps(req.texts, ensure_ascii=False)
    )
    result = call_deepseek(prompt, 0.2, "")
    try:
        text = result["answer"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        arr = _json.loads(text)
        if isinstance(arr, list) and len(arr) == len(req.texts):
            return BatchTranslateResponse(translations=[str(x) for x in arr], model=result["model"])
    except Exception:
        pass
    # 解析失败时返回原文，保证界面不崩
    return BatchTranslateResponse(translations=req.texts, model=result["model"])


# ==================== CSV 数据可视化（模块六） ====================
class VisualizeRequest(BaseModel):
    csv: str = Field(..., min_length=1, description="CSV 文本")


class VisualizeResponse(BaseModel):
    columns: list[str]
    rows: list[list]
    chart_type: str


def _normalize_csv(text: str) -> str:
    """兼容「斜杠分隔」的单行写法：若没有换行但有 /，把 / 当作行分隔。"""
    text = text.strip()
    if "\n" not in text and "/" in text:
        text = text.replace("/", "\n")
    return text


@app.post("/api/visualize", response_model=VisualizeResponse)
def visualize(req: VisualizeRequest):
    """解析 CSV，返回结构化数据与推荐图表类型。"""
    import csv as _csv
    reader = _csv.reader(io.StringIO(_normalize_csv(req.csv)))
    rows = [r for r in reader if r]
    if not rows:
        raise HTTPException(status_code=400, detail="CSV 内容为空")
    header = rows[0]
    data = rows[1:]
    chart_type = "line" if len(data) > 10 else "bar"
    return VisualizeResponse(columns=header, rows=data, chart_type=chart_type)


# ==================== LaTeX 表格生成（模块六） ====================
class LatexRequest(BaseModel):
    csv: str = Field(..., min_length=1, description="CSV 文本")


class LatexResponse(BaseModel):
    latex: str


@app.post("/api/latex", response_model=LatexResponse)
def generate_latex(req: LatexRequest):
    """把 CSV 转成可直接编译的 LaTeX 表格代码。"""
    import csv as _csv
    reader = _csv.reader(io.StringIO(_normalize_csv(req.csv)))
    rows = [r for r in reader if r]
    if not rows:
        raise HTTPException(status_code=400, detail="CSV 内容为空")
    header = rows[0]
    data = rows[1:]
    ncol = len(header)
    lines = [
        "\\begin{table}[htbp]",
        "  \\centering",
        "  \\caption{实验结果}",
        "  \\begin{tabular}{" + "l" + "c" * (ncol - 1) + "}",
        "    \\hline",
        "    " + " & ".join(header) + " \\\\",
        "    \\hline",
    ]
    for row in data:
        lines.append("    " + " & ".join(row) + " \\\\")
    lines += ["    \\hline", "  \\end{tabular}", "\\end{table}"]
    return LatexResponse(latex="\n".join(lines))


# ==================== arXiv 自动检索（模块四） ====================
class ArxivResponse(BaseModel):
    papers: list[dict]
    source: str


@app.get("/api/arxiv", response_model=ArxivResponse)
def fetch_arxiv(query: str, max_results: int = 5):
    """从 arXiv 检索论文并写入向量库；网络不可达时返回离线示例。"""
    import xml.etree.ElementTree as ET

    params = {
        "search_query": f"all:{query}",
        "max_results": max(1, min(10, max_results)),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    try:
        resp = requests.get("http://export.arxiv.org/api/query", params=params, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        papers = []
        for entry in root.findall("a:entry", ns):
            papers.append({
                "title": (entry.findtext("a:title", default="", namespaces=ns) or "").strip(),
                "summary": (entry.findtext("a:summary", default="", namespaces=ns) or "").strip(),
                "published": (entry.findtext("a:published", default="", namespaces=ns) or "")[:10],
                "id": (entry.findtext("a:id", default="", namespaces=ns) or "").strip(),
            })
        if papers and chromadb is not None:
            try:
                col = _get_collection()
                for p in papers:
                    text = f"{p['title']}\n{p['summary']}"
                    col.upsert(
                        ids=[f"arxiv:{p['id']}"],
                        documents=[text],
                        embeddings=[_hash_embed(text)],
                        metadatas=[{"source": "arXiv", "chunk": 0}],
                    )
            except Exception:
                pass
        return ArxivResponse(papers=papers, source="arxiv")
    except Exception:
        # 离线示例，明确标注来源
        sample = [
            {"title": "Attention Is All You Need", "summary": "提出 Transformer 架构，摒弃循环与卷积，完全基于自注意力。", "published": "2017-06-12", "id": "1706.03762"},
            {"title": "BERT: Pre-training of Deep Bidirectional Transformers", "summary": "双向编码器预训练，显著提升多项 NLP 任务。", "published": "2018-10-11", "id": "1810.04805"},
        ]
        return ArxivResponse(papers=sample, source="offline_sample")


# ==================== 学术润色（模块六） ====================
class PolishRequest(BaseModel):
    text: str = Field(..., min_length=1, description="待润色的学术文本")


class PolishResponse(BaseModel):
    polished: str
    model: str


@app.post("/api/polish", response_model=PolishResponse)
def polish(req: PolishRequest):
    """学术润色：纠正错误、规范术语、提升学术表达。"""
    prompt = (
        "请作为学术编辑校对并润色以下文本：\n"
        "1. 修正错别字、标点与语法错误；\n"
        "2. 指出并修正明显的事实性错误；\n"
        "3. 将口语化表达替换为规范的学术术语；\n"
        "4. 输出两部分：先给「修订后全文」，再给「修改点清单」（原句 → 修改后 + 原因）。\n\n"
        "原文：\n" + req.text
    )
    result = call_deepseek(prompt, 0.3, "")
    return PolishResponse(polished=result["answer"], model=result["model"])


# ==================== 文献引用校验（真实数据库 Crossref） ====================
class CitationRequest(BaseModel):
    citation: str = Field(..., min_length=1, description="待校验的文献引用")


class CitationCandidate(BaseModel):
    title: str
    authors: str
    year: str
    doi: str
    container: str


class CitationResponse(BaseModel):
    query: str
    candidates: list[CitationCandidate]
    source: str


@app.post("/api/verify-citation", response_model=CitationResponse)
def verify_citation(req: CitationRequest):
    """用 Crossref 检索文献，返回候选的正确记录，供用户选择替换/自定义/不替换。"""
    try:
        resp = requests.get(
            "https://api.crossref.org/works",
            params={"query.bibliographic": req.citation, "rows": 3},
            timeout=20,
            headers={"User-Agent": "zhihui-yantu/1.0"},
        )
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])
        candidates = []
        for it in items:
            title = (it.get("title") or [""])[0]
            authors = ", ".join(
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in (it.get("author") or [])[:5]
            )
            year = ""
            for k in ("published-print", "published-online", "issued"):
                parts = (it.get(k) or {}).get("date-parts")
                if parts and parts[0] and parts[0][0]:
                    year = str(parts[0][0])
                    break
            candidates.append({
                "title": title,
                "authors": authors,
                "year": year,
                "doi": it.get("DOI", ""),
                "container": (it.get("container-title") or [""])[0],
            })
        return CitationResponse(query=req.citation, candidates=candidates, source="crossref")
    except Exception:
        return CitationResponse(query=req.citation, candidates=[], source="offline")


# ==================== 多源文献检索（Crossref / OpenAlex / Europe PMC / DBLP / arXiv） ====================
from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: E402


class LiteratureRequest(BaseModel):
    query: str = Field(..., min_length=1, description="检索关键词")
    limit: int = Field(3, ge=1, le=10, description="每个来源返回条数")


class LiteratureItem(BaseModel):
    source: str
    title: str
    authors: str
    year: str
    doi: str = ""
    url: str = ""


class LiteratureResponse(BaseModel):
    query: str
    results: list[LiteratureItem]
    sources_ok: list[str]
    sources_fail: list[str]


def _lit_crossref(q: str, n: int):
    resp = requests.get(
        "https://api.crossref.org/works",
        params={"query.bibliographic": q, "rows": n},
        timeout=20,
        headers={"User-Agent": "zhihui-yantu/1.0"},
    )
    resp.raise_for_status()
    out = []
    for it in resp.json().get("message", {}).get("items", []):
        year = ""
        for k in ("published-print", "published-online", "issued"):
            parts = (it.get(k) or {}).get("date-parts")
            if parts and parts[0] and parts[0][0]:
                year = str(parts[0][0])
                break
        doi = it.get("DOI", "")
        out.append({
            "source": "Crossref",
            "title": (it.get("title") or [""])[0],
            "authors": ", ".join(
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in (it.get("author") or [])[:5]
            ),
            "year": year,
            "doi": doi,
            "url": f"https://doi.org/{doi}" if doi else "",
        })
    return out


def _lit_openalex(q: str, n: int):
    resp = requests.get(
        "https://api.openalex.org/works",
        params={"search": q, "per-page": n},
        timeout=20,
    )
    resp.raise_for_status()
    out = []
    for it in resp.json().get("results", []):
        doi = (it.get("doi") or "").replace("https://doi.org/", "")
        out.append({
            "source": "OpenAlex",
            "title": it.get("title") or "",
            "authors": ", ".join(
                a.get("author", {}).get("display_name", "")
                for a in (it.get("authorships") or [])[:5]
            ),
            "year": str(it.get("publication_year") or ""),
            "doi": doi,
            "url": it.get("doi") or "",
        })
    return out


def _lit_europepmc(q: str, n: int):
    resp = requests.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": q, "format": "json", "pageSize": n},
        timeout=20,
    )
    resp.raise_for_status()
    out = []
    for it in resp.json().get("resultList", {}).get("result", []):
        doi = it.get("doi", "")
        out.append({
            "source": "Europe PMC",
            "title": it.get("title", ""),
            "authors": it.get("authorString", ""),
            "year": str(it.get("pubYear", "")),
            "doi": doi,
            "url": f"https://doi.org/{doi}" if doi else "",
        })
    return out


def _lit_arxiv(q: str, n: int):
    import xml.etree.ElementTree as ET

    resp = requests.get(
        "http://export.arxiv.org/api/query",
        params={"search_query": f"all:{q}", "max_results": n},
        timeout=20,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for entry in root.findall("a:entry", ns):
        out.append({
            "source": "arXiv",
            "title": (entry.findtext("a:title", default="", namespaces=ns) or "").strip(),
            "authors": ", ".join(
                a.findtext("a:name", default="", namespaces=ns).strip()
                for a in entry.findall("a:author", ns)
            ),
            "year": (entry.findtext("a:published", default="", namespaces=ns) or "")[:4],
            "doi": "",
            "url": (entry.findtext("a:id", default="", namespaces=ns) or "").strip(),
        })
    return out


_LIT_SOURCES = {
    "Crossref": _lit_crossref,
    "OpenAlex": _lit_openalex,
    "Europe PMC": _lit_europepmc,
    "arXiv": _lit_arxiv,
}


@app.post("/api/literature-search", response_model=LiteratureResponse)
def literature_search(req: LiteratureRequest):
    """并行检索多个权威文献库，合并结果。"""
    results = []
    ok, fail = [], []
    with ThreadPoolExecutor(max_workers=len(_LIT_SOURCES)) as ex:
        futures = {ex.submit(fn, req.query, req.limit): name for name, fn in _LIT_SOURCES.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                results.extend(fut.result())
                ok.append(name)
            except Exception:
                fail.append(name)
    return LiteratureResponse(query=req.query, results=results, sources_ok=ok, sources_fail=fail)


# ==================== 文献库自由搜索（标题/作者/片段） ====================
class LibSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="搜索词：标题、作者或文献片段")
    limit: int = Field(5, ge=1, le=20, description="每个来源返回条数")


class LibSearchItem(BaseModel):
    source: str
    title: str
    authors: str
    year: str
    doi: str = ""
    url: str = ""
    relevance: float = 0.0


class LibSearchResponse(BaseModel):
    query: str
    count: int
    results: list[LibSearchItem]


@app.post("/api/library-search", response_model=LibSearchResponse)
def library_search(req: LibSearchRequest):
    """多源自由搜索：支持标题、作者、文献片段，按相关度排序。"""
    query = req.query.strip()
    qvec = _hash_embed(query)

    raw = []
    with ThreadPoolExecutor(max_workers=len(_LIT_SOURCES)) as ex:
        futures = {ex.submit(fn, query, req.limit): name for name, fn in _LIT_SOURCES.items()}
        for fut in as_completed(futures):
            try:
                raw.extend(fut.result())
            except Exception:
                pass

    results = []
    for it in raw:
        cand = f"{it.get('title', '')} {it.get('authors', '')} {it.get('year', '')}"
        rel = float(_cosine(qvec, _hash_embed(cand)))
        # 精确包含加分
        qlow = query.lower()
        if qlow and qlow in (it.get("title", "") or "").lower():
            rel = min(1.0, rel + 0.15)
        results.append({
            "source": it.get("source", ""),
            "title": it.get("title", ""),
            "authors": it.get("authors", ""),
            "year": it.get("year", ""),
            "doi": it.get("doi", ""),
            "url": it.get("url", ""),
            "relevance": round(rel, 3),
        })

    results.sort(key=lambda x: x["relevance"], reverse=True)
    return LibSearchResponse(query=query, count=len(results), results=results[:20])


# ==================== 论文查重（基于开源文献库） ====================
class PlagiarismRequest(BaseModel):
    text: str = Field(..., min_length=20, max_length=100000, description="待查重的文本（20 ~ 100,000 字）")


class PlagiarismMatch(BaseModel):
    source: str
    title: str
    year: str
    similarity: float
    url: str


class PlagiarismParagraph(BaseModel):
    text: str
    similarity: float


class PlagiarismResponse(BaseModel):
    text_len: int
    max_similarity: float
    risk_level: str
    matches: list[PlagiarismMatch]
    paragraphs: list[PlagiarismParagraph] = []
    sources_checked: list[str]


def _split_paragraphs(text: str, max_len: int = 300) -> list[str]:
    """把长文本切分为段落（兼顾换行与句子边界）。"""
    raw = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    out = []
    for p in raw:
        if len(p) <= max_len:
            out.append(p)
            continue
        sents = re.split(r"(?<=[。！？.!?])\s*", p)
        buf = ""
        for s in sents:
            if len(buf) + len(s) > max_len and buf:
                out.append(buf.strip())
                buf = s
            else:
                buf += s
        if buf.strip():
            out.append(buf.strip())
    return out


def _openalex_abstract(it) -> str:
    inv = it.get("abstract_inverted_index")
    if not inv:
        return ""
    pairs = []
    for word, positions in inv.items():
        for pos in positions:
            pairs.append((pos, word))
    pairs.sort()
    return " ".join(w for _, w in pairs)


def _plag_openalex(qvec, query, kw):
    resp = requests.get(
        "https://api.openalex.org/works",
        params={"search": query, "per-page": 5},
        timeout=15,
    )
    resp.raise_for_status()
    out = []
    for it in resp.json().get("results", []):
        cand = (it.get("title") or "") + " " + _openalex_abstract(it)
        out.append({
            "source": "OpenAlex",
            "title": it.get("title") or "",
            "year": str(it.get("publication_year") or ""),
            "similarity": round(float(_cosine(qvec, _hash_embed(cand))), 3),
            "url": it.get("doi") or "",
        })
    return out


def _plag_arxiv(qvec, query, kw):
    import xml.etree.ElementTree as ET

    resp = requests.get(
        "http://export.arxiv.org/api/query",
        params={"search_query": f"all:{query}", "max_results": 5},
        timeout=15,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for entry in root.findall("a:entry", ns):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        summary = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
        out.append({
            "source": "arXiv",
            "title": title,
            "year": (entry.findtext("a:published", default="", namespaces=ns) or "")[:4],
            "similarity": round(float(_cosine(qvec, _hash_embed(title + " " + summary))), 3),
            "url": (entry.findtext("a:id", default="", namespaces=ns) or "").strip(),
        })
    return out


def _plag_europepmc(qvec, query, kw):
    resp = requests.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": query, "format": "json", "pageSize": 5},
        timeout=15,
    )
    resp.raise_for_status()
    out = []
    for it in resp.json().get("resultList", {}).get("result", []):
        cand = (it.get("title") or "") + " " + (it.get("abstractText") or "")
        doi = it.get("doi", "")
        out.append({
            "source": "Europe PMC",
            "title": it.get("title", ""),
            "year": str(it.get("pubYear", "")),
            "similarity": round(float(_cosine(qvec, _hash_embed(cand))), 3),
            "url": f"https://doi.org/{doi}" if doi else "",
        })
    return out


def _plag_doaj(qvec, query, kw):
    from urllib.parse import quote as _quote

    resp = requests.get(
        f"https://doaj.org/api/search/articles/{_quote(query, safe='')}",
        params={"pageSize": 5},
        timeout=15,
    )
    resp.raise_for_status()
    out = []
    for it in resp.json().get("results", []):
        b = it.get("bibjson", {})
        cand = (b.get("title") or "") + " " + (b.get("abstract") or "")
        doi = b.get("doi", "") or ""
        out.append({
            "source": "DOAJ",
            "title": b.get("title", "") or "",
            "year": str(b.get("year", "") or ""),
            "similarity": round(float(_cosine(qvec, _hash_embed(cand))), 3),
            "url": f"https://doi.org/{doi}" if doi else "",
        })
    return out


def _plag_zenodo(qvec, query, kw):
    resp = requests.get(
        "https://zenodo.org/api/records",
        params={"q": query, "size": 5},
        timeout=15,
    )
    resp.raise_for_status()
    out = []
    for h in resp.json().get("hits", {}).get("hits", []):
        m = h.get("metadata", {})
        desc = re.sub(r"<[^>]+>", " ", m.get("description", "") or "")
        cand = (m.get("title", "") or "") + " " + desc
        out.append({
            "source": "Zenodo",
            "title": m.get("title", "") or "",
            "year": (m.get("publication_date", "") or "")[:4],
            "similarity": round(float(_cosine(qvec, _hash_embed(cand))), 3),
            "url": h.get("links", {}).get("self_html", "") or "",
        })
    return out


def _plag_crossref(qvec, query, kw):
    resp = requests.get(
        "https://api.crossref.org/works",
        params={"query.bibliographic": query, "rows": 5},
        timeout=15,
        headers={"User-Agent": "zhihui-yantu/1.0"},
    )
    resp.raise_for_status()
    out = []
    for it in resp.json().get("message", {}).get("items", []):
        year = ""
        for k in ("published-print", "published-online", "issued"):
            parts = (it.get(k) or {}).get("date-parts")
            if parts and parts[0] and parts[0][0]:
                year = str(parts[0][0])
                break
        title = (it.get("title") or [""])[0]
        doi = it.get("DOI", "")
        out.append({
            "source": "Crossref",
            "title": title,
            "year": year,
            "similarity": round(float(_cosine(qvec, _hash_embed(title))), 3),
            "url": f"https://doi.org/{doi}" if doi else "",
        })
    return out


def _plag_openaire(qvec, query, kw):
    def _val(v):
        if isinstance(v, list):
            v = v[0] if v else None
        if isinstance(v, dict):
            return v.get("$", "") or ""
        return v or ""

    resp = requests.get(
        "https://api.openaire.eu/search/publications",
        params={"title": kw, "size": 5, "format": "json"},
        timeout=15,
    )
    resp.raise_for_status()
    _rjson = resp.json() or {}
    _res_obj = ((_rjson.get("response") or {}).get("results") or {}).get("result") or []
    res = [_res_obj] if isinstance(_res_obj, dict) else _res_obj
    out = []
    for it in res:
        oaf = (it.get("metadata") or {}).get("oaf:entity", {}).get("oaf:result", {}) or {}
        title = _val(oaf.get("title"))
        desc = _val(oaf.get("description"))
        date = _val(oaf.get("dateofacceptance"))
        out.append({
            "source": "OpenAIRE",
            "title": title,
            "year": (date or "")[:4],
            "similarity": round(float(_cosine(qvec, _hash_embed(title + " " + desc))), 3),
            "url": "",
        })
    return out


def _plag_pubmed(qvec, query, kw):
    r = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={"db": "pubmed", "term": kw, "retmode": "json", "retmax": 5},
        timeout=15,
    )
    r.raise_for_status()
    ids = r.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    r2 = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
        timeout=15,
    )
    r2.raise_for_status()
    d = r2.json().get("result", {})
    out = []
    for pid in ids:
        rec = d.get(pid, {})
        title = (rec.get("title", "") or "").rstrip(".")
        out.append({
            "source": "PubMed",
            "title": title,
            "year": (rec.get("pubdate", "") or "")[:4],
            "similarity": round(float(_cosine(qvec, _hash_embed(title))), 3),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
        })
    return out


_PLAG_SOURCES = {
    "OpenAlex": _plag_openalex,
    "arXiv": _plag_arxiv,
    "Europe PMC": _plag_europepmc,
    "DOAJ": _plag_doaj,
    "Zenodo": _plag_zenodo,
    "Crossref": _plag_crossref,
    "OpenAIRE": _plag_openaire,
    "PubMed": _plag_pubmed,
}


@app.post("/api/plagiarism-check", response_model=PlagiarismResponse)
def plagiarism_check(req: PlagiarismRequest):
    """整篇论文查重：并行比对 8 个开放文献库，并做段落级相似度分析。"""
    text = req.text.strip()
    qvec = _hash_embed(text)
    _flat = " ".join(text.split())
    query = _flat[:180]
    kw = " ".join(_flat.split()[:12])

    matches = []
    checked = []
    with ThreadPoolExecutor(max_workers=len(_PLAG_SOURCES)) as ex:
        futures = {ex.submit(fn, qvec, query, kw): name for name, fn in _PLAG_SOURCES.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                matches.extend(fut.result())
                checked.append(name)
            except Exception:
                pass

    matches.sort(key=lambda m: m["similarity"], reverse=True)
    top = matches[:5]
    max_sim = top[0]["similarity"] if top else 0.0

    # 段落级相似度：把全文按段落切分，逐段比对候选文献标题
    para_scores = []
    if top:
        cand_vecs = [_hash_embed(m["title"]) for m in top]
        for p in _split_paragraphs(text):
            if len(p) < 30:
                continue
            pvec = _hash_embed(p)
            best = max((float(_cosine(pvec, cvec)) for cvec in cand_vecs), default=0.0)
            para_scores.append(PlagiarismParagraph(text=p[:200], similarity=round(best, 3)))
        para_scores.sort(key=lambda x: x.similarity, reverse=True)
        para_scores = para_scores[:5]

    risk = "高" if max_sim >= 0.6 else ("中" if max_sim >= 0.4 else "低")

    return PlagiarismResponse(
        text_len=len(text),
        max_similarity=max_sim,
        risk_level=risk,
        matches=top,
        paragraphs=para_scores,
        sources_checked=checked,
    )



@app.post("/api/extract-text")
async def extract_text(file: UploadFile = File(...)):
    """提取上传文件（PDF/TXT/MD）的纯文本，供整篇论文查重使用。"""
    content = await file.read()
    name = (file.filename or "").lower()
    if name.endswith(".pdf"):
        text = ""
        try:
            reader = PdfReader(io.BytesIO(content))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            text = ""
        if len(text.strip()) < 50:
            try:
                text = _ocr_pdf(content)
            except Exception:
                pass
    else:
        text = content.decode("utf-8", errors="ignore")
    return {"text": text, "chars": len(text)}


# ==================== 用户注册 / 登录 / 资料库 ====================
class AuthRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32, description="用户名")
    password: str = Field(..., min_length=4, max_length=64, description="密码")


class AuthResponse(BaseModel):
    ok: bool
    username: str
    token: str
    message: str = ""


def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


@app.post("/api/register", response_model=AuthResponse)
def register(req: AuthRequest):
    """用户注册，信息持久化到 SQLite。"""
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (req.username, _hash_pw(req.password), datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="用户名已存在")
    finally:
        conn.close()
    return AuthResponse(ok=True, username=req.username, token=secrets.token_hex(16), message="注册成功")


@app.post("/api/login", response_model=AuthResponse)
def login(req: AuthRequest):
    """用户登录，校验密码并更新最近登录时间。"""
    conn = sqlite3.connect(_DB_PATH)
    row = conn.execute("SELECT password_hash FROM users WHERE username=?", (req.username,)).fetchone()
    if not row or row[0] != _hash_pw(req.password):
        conn.close()
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    conn.execute(
        "UPDATE users SET last_login=? WHERE username=?",
        (datetime.now().isoformat(timespec="seconds"), req.username),
    )
    conn.commit()
    conn.close()
    return AuthResponse(ok=True, username=req.username, token=secrets.token_hex(16), message="登录成功")


@app.get("/api/users")
def list_users():
    """用户资料库：返回全部注册用户（演示用）。"""
    conn = sqlite3.connect(_DB_PATH)
    rows = conn.execute(
        "SELECT id, username, created_at, last_login FROM users ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return {
        "count": len(rows),
        "users": [
            {"id": r[0], "username": r[1], "created_at": r[2], "last_login": r[3]}
            for r in rows
        ],
    }


# ==================== 学科资料库 + 用户浏览历史 ====================
class HistoryRequest(BaseModel):
    username: str = Field(..., min_length=1)
    subject_id: str = Field(..., min_length=1)
    subject_name: str = Field(..., min_length=1)
    item_title: str = ""
    item_url: str = ""
    note: str = ""


class HistoryUpdate(BaseModel):
    note: str = ""


@app.get("/api/subjects")
def list_subjects():
    """返回全部学科分类。"""
    return {"subjects": _SUBJECTS}


@app.get("/api/subjects/{sid}/literature")
def subject_literature(sid: str):
    """按学科/子领域检索相关文献（OpenAlex + arXiv 并行）。"""
    parent, child = _find_subject(sid)
    if not parent:
        raise HTTPException(status_code=404, detail="学科不存在")
    subj = child or parent
    keyword = subj["keyword"]

    def _openalex():
        r = requests.get(
            "https://api.openalex.org/works",
            params={"search": keyword, "per-page": 6, "sort": "cited_by_count:desc"},
            timeout=20,
        )
        r.raise_for_status()
        out = []
        for it in r.json().get("results", []):
            doi = (it.get("doi") or "").replace("https://doi.org/", "")
            out.append({
                "source": "OpenAlex",
                "title": it.get("title") or "",
                "year": str(it.get("publication_year") or ""),
                "authors": ", ".join(
                    a.get("author", {}).get("display_name", "")
                    for a in (it.get("authorships") or [])[:3]
                ),
                "url": it.get("doi") or (f"https://doi.org/{doi}" if doi else ""),
                "cited": it.get("cited_by_count") or 0,
            })
        return out

    def _arxiv():
        import xml.etree.ElementTree as ET

        r = requests.get(
            "http://export.arxiv.org/api/query",
            params={"search_query": f"all:{keyword}", "max_results": 6, "sortBy": "relevance"},
            timeout=20,
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        out = []
        for e in root.findall("a:entry", ns):
            out.append({
                "source": "arXiv",
                "title": (e.findtext("a:title", default="", namespaces=ns) or "").strip(),
                "year": (e.findtext("a:published", default="", namespaces=ns) or "")[:4],
                "authors": ", ".join(
                    a.findtext("a:name", default="", namespaces=ns).strip()
                    for a in e.findall("a:author", ns)[:3]
                ),
                "url": (e.findtext("a:id", default="", namespaces=ns) or "").strip(),
                "cited": 0,
            })
        return out

    items = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_openalex), ex.submit(_arxiv)]
        for f in as_completed(futs):
            try:
                items.extend(f.result())
            except Exception:
                pass
    items.sort(key=lambda x: x.get("cited", 0), reverse=True)
    return {"subject": subj, "items": items[:10]}


@app.post("/api/history")
def add_history(req: HistoryRequest):
    """记录一次学科浏览（绑定用户名）。"""
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "INSERT INTO history (username, subject_id, subject_name, item_title, item_url, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            req.username, req.subject_id, req.subject_name, req.item_title, req.item_url, req.note,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"ok": True, "id": rid}


@app.get("/api/history")
def get_history(username: str):
    """获取某用户的浏览历史（按时间倒序）。"""
    conn = sqlite3.connect(_DB_PATH)
    rows = conn.execute(
        "SELECT id, subject_id, subject_name, item_title, item_url, note, created_at "
        "FROM history WHERE username=? ORDER BY id DESC",
        (username,),
    ).fetchall()
    conn.close()
    return {
        "username": username,
        "count": len(rows),
        "records": [
            {
                "id": r[0], "subject_id": r[1], "subject_name": r[2], "item_title": r[3],
                "item_url": r[4], "note": r[5], "created_at": r[6],
            }
            for r in rows
        ],
    }


@app.put("/api/history/{rid}")
def update_history(rid: int, req: HistoryUpdate):
    """修改历史记录的备注。"""
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("UPDATE history SET note=? WHERE id=?", (req.note, rid))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/history/{rid}")
def delete_history(rid: int):
    """删除一条历史记录。"""
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("DELETE FROM history WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ==================== 文献完整内容（全文/摘要） ====================
class ArticleDetailRequest(BaseModel):
    source: str = ""
    url: str = ""
    title: str = ""


class ArticleDetailResponse(BaseModel):
    title: str
    authors: str
    year: str
    source: str
    abstract: str
    fulltext: str = ""
    url: str
    doi: str


@app.post("/api/article-detail", response_model=ArticleDetailResponse)
def article_detail(req: ArticleDetailRequest):
    """获取文献完整信息（含完整摘要/正文），供详情页与翻译使用。"""
    src = (req.source or "").lower()
    url = req.url or ""
    doi = ""

    # arXiv：按 id 拉取完整摘要
    if "arxiv" in src or "arxiv.org" in url:
        import xml.etree.ElementTree as ET

        m = re.search(r"(\d{4}\.\d{4,5})", url)
        if m:
            try:
                r = requests.get(
                    "http://export.arxiv.org/api/query",
                    params={"id_list": m.group(1)},
                    timeout=20,
                )
                r.raise_for_status()
                root = ET.fromstring(r.text)
                ns = {"a": "http://www.w3.org/2005/Atom"}
                entry = root.find("a:entry", ns)
                if entry is not None:
                    abstract = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
                    # 尝试下载 PDF 提取完整正文
                    fulltext = ""
                    try:
                        pr = requests.get(f"https://arxiv.org/pdf/{m.group(1)}", timeout=40)
                        if pr.ok:
                            import pymupdf as fitz

                            doc = fitz.open(stream=pr.content, filetype="pdf")
                            fulltext = "\n".join(page.get_text() for page in doc).strip()
                    except Exception:
                        fulltext = ""
                    return ArticleDetailResponse(
                        title=(entry.findtext("a:title", default="", namespaces=ns) or "").strip(),
                        authors=", ".join(
                            a.findtext("a:name", default="", namespaces=ns).strip()
                            for a in entry.findall("a:author", ns)
                        ),
                        year=(entry.findtext("a:published", default="", namespaces=ns) or "")[:4],
                        source="arXiv",
                        abstract=abstract,
                        fulltext=fulltext,
                        url=url,
                        doi="",
                    )
            except Exception:
                pass

    # OpenAlex：按 DOI 拉取完整摘要
    m = re.search(r"doi\.org/(.+)", url)
    if m:
        doi = m.group(1)
        try:
            r = requests.get(f"https://api.openalex.org/works/https://doi.org/{doi}", timeout=20)
            if r.ok:
                it = r.json()
                return ArticleDetailResponse(
                    title=it.get("title") or req.title,
                    authors=", ".join(
                        a.get("author", {}).get("display_name", "")
                        for a in (it.get("authorships") or [])[:8]
                    ),
                    year=str(it.get("publication_year") or ""),
                    source="OpenAlex",
                    abstract=_openalex_abstract(it),
                    url=url,
                    doi=doi,
                )
        except Exception:
            pass

    # 兜底：返回已知信息
    return ArticleDetailResponse(
        title=req.title,
        authors="",
        year="",
        source=req.source,
        abstract="",
        url=url,
        doi=doi,
    )


# ==================== 团队协作 + 文件编辑 ====================
class TeamCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    owner: str = Field(..., min_length=1)


class TeamJoinRequest(BaseModel):
    code: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)


class TeamInviteRequest(BaseModel):
    code: str = Field(..., min_length=1)
    owner: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    role: str = Field("viewer", description="viewer / editor")


class DocCreateRequest(BaseModel):
    username: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)


class DocUpdateRequest(BaseModel):
    username: str = Field(..., min_length=1)
    content: str = ""


def _team_role(code: str, username: str):
    """返回 (team_id, role)，非成员返回 None。"""
    conn = sqlite3.connect(_DB_PATH)
    row = conn.execute(
        "SELECT t.id, m.role FROM teams t JOIN team_members m ON m.team_id = t.id "
        "WHERE t.code=? AND m.username=?",
        (code, username),
    ).fetchone()
    conn.close()
    return row


@app.post("/api/teams")
def create_team(req: TeamCreateRequest):
    """创建团队，生成唯一团队代码，创建者为 owner。"""
    code = secrets.token_hex(4).upper()
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute(
            "INSERT INTO teams (name, code, owner, created_at) VALUES (?, ?, ?, ?)",
            (req.name, code, req.owner, datetime.now().isoformat(timespec="seconds")),
        )
        team_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO team_members (team_id, username, role, joined_at) VALUES (?, ?, ?, ?)",
            (team_id, req.owner, "owner", datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "code": code, "name": req.name, "owner": req.owner}


@app.post("/api/teams/join")
def join_team(req: TeamJoinRequest):
    """用团队代码加入（默认 viewer）。"""
    conn = sqlite3.connect(_DB_PATH)
    row = conn.execute("SELECT id FROM teams WHERE code=?", (req.code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="团队代码不存在")
    team_id = row[0]
    try:
        conn.execute(
            "INSERT INTO team_members (team_id, username, role, joined_at) VALUES (?, ?, ?, ?)",
            (team_id, req.username, "viewer", datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="你已经是该团队成员")
    conn.close()
    return {"ok": True, "team_id": team_id, "role": "viewer"}


@app.post("/api/teams/invite")
def invite_member(req: TeamInviteRequest):
    """owner 邀请成员并指定权限（viewer / editor）。"""
    conn = sqlite3.connect(_DB_PATH)
    row = conn.execute("SELECT id, owner FROM teams WHERE code=?", (req.code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="团队代码不存在")
    team_id, owner = row
    if owner != req.owner:
        conn.close()
        raise HTTPException(status_code=403, detail="只有创建者可以邀请成员")
    role = req.role if req.role in ("viewer", "editor") else "viewer"
    try:
        conn.execute(
            "INSERT INTO team_members (team_id, username, role, joined_at) VALUES (?, ?, ?, ?)",
            (team_id, req.username, role, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="该成员已在团队中")
    conn.close()
    return {"ok": True, "username": req.username, "role": role}


@app.get("/api/teams/mine")
def my_teams(username: str):
    """返回用户所属的团队列表。"""
    conn = sqlite3.connect(_DB_PATH)
    rows = conn.execute(
        "SELECT t.code, t.name, t.owner, m.role FROM teams t "
        "JOIN team_members m ON m.team_id = t.id WHERE m.username=? ORDER BY t.id DESC",
        (username,),
    ).fetchall()
    conn.close()
    return {"teams": [{"code": r[0], "name": r[1], "owner": r[2], "role": r[3]} for r in rows]}


@app.get("/api/teams/{code}")
def team_detail(code: str, username: str):
    """团队详情：成员 + 文档列表（仅成员可见）。"""
    role_row = _team_role(code, username)
    if not role_row:
        raise HTTPException(status_code=403, detail="你不是该团队成员")
    team_id = role_row[0]
    conn = sqlite3.connect(_DB_PATH)
    team = conn.execute("SELECT name, owner FROM teams WHERE id=?", (team_id,)).fetchone()
    members = conn.execute(
        "SELECT username, role, joined_at FROM team_members WHERE team_id=? ORDER BY id", (team_id,)
    ).fetchall()
    docs = conn.execute(
        "SELECT id, title, updated_by, updated_at FROM team_docs WHERE team_id=? ORDER BY id DESC",
        (team_id,),
    ).fetchall()
    conn.close()
    return {
        "code": code,
        "name": team[0],
        "owner": team[1],
        "my_role": role_row[1],
        "members": [{"username": m[0], "role": m[1], "joined_at": m[2]} for m in members],
        "docs": [{"id": d[0], "title": d[1], "updated_by": d[2], "updated_at": d[3]} for d in docs],
    }


@app.post("/api/teams/{code}/docs")
def create_doc(code: str, req: DocCreateRequest):
    role_row = _team_role(code, req.username)
    if not role_row:
        raise HTTPException(status_code=403, detail="你不是该团队成员")
    if role_row[1] not in ("owner", "editor"):
        raise HTTPException(status_code=403, detail="你的权限不足（仅可查看）")
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "INSERT INTO team_docs (team_id, title, content, updated_by, updated_at) VALUES (?, ?, ?, ?, ?)",
        (role_row[0], req.title, "", req.username, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    did = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"ok": True, "id": did}


@app.get("/api/teams/{code}/docs/{did}")
def get_doc(code: str, did: int, username: str):
    role_row = _team_role(code, username)
    if not role_row:
        raise HTTPException(status_code=403, detail="你不是该团队成员")
    conn = sqlite3.connect(_DB_PATH)
    row = conn.execute(
        "SELECT id, title, content, updated_by, updated_at FROM team_docs WHERE id=? AND team_id=?",
        (did, role_row[0]),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"id": row[0], "title": row[1], "content": row[2], "updated_by": row[3], "updated_at": row[4]}


@app.put("/api/teams/{code}/docs/{did}")
def update_doc(code: str, did: int, req: DocUpdateRequest):
    role_row = _team_role(code, req.username)
    if not role_row:
        raise HTTPException(status_code=403, detail="你不是该团队成员")
    if role_row[1] not in ("owner", "editor"):
        raise HTTPException(status_code=403, detail="你的权限不足（仅可查看）")
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "UPDATE team_docs SET content=?, updated_by=?, updated_at=? WHERE id=? AND team_id=?",
        (req.content, req.username, datetime.now().isoformat(timespec="seconds"), did, role_row[0]),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/teams/{code}/docs/{did}")
def delete_doc(code: str, did: int, username: str):
    role_row = _team_role(code, username)
    if not role_row:
        raise HTTPException(status_code=403, detail="你不是该团队成员")
    if role_row[1] != "owner":
        raise HTTPException(status_code=403, detail="只有创建者可以删除文档")
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("DELETE FROM team_docs WHERE id=? AND team_id=?", (did, role_row[0]))
    conn.commit()
    conn.close()
    return {"ok": True}
