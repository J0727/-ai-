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
import time
import hashlib
import requests
from pypdf import PdfReader

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


# ==================== 学术翻译（模块三） ====================
class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, description="待翻译文本")
    target: str = Field("en", description="目标语言：en 或 zh")


class TranslateResponse(BaseModel):
    translated: str
    model: str


@app.post("/api/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest):
    """学术文本中英互译，保留专业术语与代码。"""
    target_name = "英文" if req.target == "en" else "中文"
    prompt = f"请将以下学术文本翻译为{target_name}，保留专业术语、公式与代码不译：\n\n{req.text}"
    result = call_deepseek(prompt, 0.3, "")
    return TranslateResponse(translated=result["answer"], model=result["model"])


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
