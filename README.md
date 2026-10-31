# 智汇研途 - AI科研辅助平台

传智杯AI大模型挑战赛参赛作品。

> **AI 辅助开发声明**：本项目使用 DeepSeek 作为 AI 辅助开发工具，用于生成代码骨架、页面布局与基础逻辑；所有代码均经过人工审核、调试与修改，关键逻辑（API 调用、边界处理、错误重试）由人工确认，确保可稳定运行。

## 项目简介

智汇研途是一个基于**多智能体协作**与 **RAG 检索增强**的科研辅助平台，覆盖「文献导入 → 问答溯源 → 引用图谱 → 综述生成 → 写作辅助 → 数据可视化」的完整科研工作流。

## 核心功能

- **多智能体协作**：检索员 / 总结员 / 批判员分工处理科研任务，工作流可视化
- **PDF 文献导入**：支持标准文本 PDF 与扫描件（自动 OCR）
- **抗幻觉 RAG**：基于 ChromaDB 的语义检索，先查文献再生成
- **问答溯源**：回答附带参考来源（文件 + 片段号），结论可核验
- **引用图谱**：基于相似度构建文献关系网络，挖掘「基石节点」
- **文献综述 / 论文大纲**：基于已上传文献一键生成
- **学术翻译**：中英学术文本互译
- **数据可视化**：CSV → 柱状图 / 折线图；CSV → LaTeX 表格
- **arXiv 检索**：调用 arXiv API 抓取论文并入库（离线可兜底）
- **PDF 版式阅读**：浏览器原生渲染，保留原始排版
- **真实大模型接入**：DeepSeek API，含超时重试与失败降级

## 技术栈

- 前端：HTML + TailwindCSS + Font Awesome + Chart.js
- 后端：FastAPI + ChromaDB + pypdf + PyMuPDF + RapidOCR
- 模型：DeepSeek Chat API

## 目录结构

```
.
├── README.md
├── requirements.txt
├── .gitignore
├── frontend/
│   └── index.html            # 前端界面（全部功能入口）
├── backend/
│   ├── main.py               # FastAPI 后端（12 个接口）
│   ├── .env.example          # 环境变量示例
│   └── 启动后端.bat           # 一键启动脚本（Windows）
└── docs/
    ├── 技术文档.docx / .pdf
    ├── 作品介绍文档.docx / .pdf
    ├── 演示视频脚本-最终版.md
    ├── 技术报告大纲.md
    ├── 演示视频脚本.md
    └── 测试报告.md
```

## 快速启动

### 1. 安装后端依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

进入 `backend/` 目录，复制 `.env.example` 为 `.env`，填入你的 DeepSeek API Key：

```
DEEPSEEK_API_KEY=你的Key
```

### 3. 启动后端（二选一）

- **Windows 双击**：`backend/启动后端.bat`
- **命令行**：
  ```bash
  cd backend
  uvicorn main:app --host 127.0.0.1 --port 8000
  ```

服务运行在 `http://127.0.0.1:8000`，接口文档见 `http://127.0.0.1:8000/docs`。

### 4. 打开前端

用浏览器打开 `frontend/index.html`，先「上传文献 PDF」，再进行问答、图谱、综述、写作等操作。后端未启动时前端会自动回退模拟回复。

## 后端接口（12 个）

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | /health | 健康检查 |
| POST | /api/chat | DeepSeek 对话（含 RAG 上下文与来源） |
| POST | /api/rag/ingest | 写入文献片段 |
| POST | /api/rag/search | 语义检索 |
| POST | /api/upload | 上传 PDF（文本 + OCR） |
| POST | /api/writing | 生成论文大纲 |
| POST | /api/survey | 生成文献综述 |
| GET | /api/graph | 引用图谱 + 基石节点 |
| POST | /api/translate | 学术翻译 |
| POST | /api/visualize | CSV → 图表数据 |
| POST | /api/latex | CSV → LaTeX 表格 |
| GET | /api/arxiv | arXiv 检索（离线兜底） |
