# 智汇研途 - AI科研辅助平台

传智杯AI大模型挑战赛参赛作品。

> **AI 辅助开发声明**：本项目使用 DeepSeek 作为 AI 辅助开发工具，用于生成代码骨架、页面布局与基础逻辑；所有代码均经过人工审核、调试与修改，关键逻辑（API 调用、边界处理、错误重试）由人工确认，确保可稳定运行。

## 项目简介

智汇研途是一个基于**多智能体协作**的科研辅助平台，通过「检索员 → 总结员 → 批判员」三个智能体分工协作，结合 **RAG 文献检索增强**，帮助科研人员快速完成文献调研、综述总结与逻辑校验，缓解大模型幻觉问题。

## 核心功能

- **多智能体协作**：检索员（Retriever）、总结员（Summarizer）、批判员（Critic）分工处理科研任务
- **RAG 文献检索增强**：基于 ChromaDB 向量库的文献检索，解决大模型幻觉
- **引用来源可视化**：Chart.js 展示文献来源分布（arXiv、PubMed、IEEE Xplore 等）
- **真实大模型接入**：通过 DeepSeek API 返回真实科研回复，失败自动回退模拟回复
- **智能体工作流可视化**：右侧面板实时展示三个智能体的运行状态

## 技术栈

- 前端：HTML + TailwindCSS + Font Awesome + Chart.js
- 后端：FastAPI + ChromaDB + LangChain + PyPDF2
- 模型：DeepSeek Chat API

## 目录结构

```
.
├── README.md
├── requirements.txt
├── .gitignore
├── frontend/
│   └── index.html            # 前端界面（聊天交互 + 工作流可视化）
├── backend/
│   ├── main.py               # FastAPI 后端服务（DeepSeek API + RAG 检索）
│   └── .env.example          # 环境变量示例
└── docs/
    ├── 技术文档.docx / 技术文档.pdf   # 正式技术文档（PDF ≤ 30 页）
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

### 3. 启动后端服务

```bash
cd backend
uvicorn main:app --reload
```

服务默认运行在 `http://127.0.0.1:8000`，可通过 `http://127.0.0.1:8000/docs` 查看接口文档。

### 4. 打开前端

用浏览器直接打开 `frontend/index.html`，输入研究问题即可开始使用。后端未启动时，前端会自动回退到模拟回复。

## 后端接口

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | /health | 健康检查 |
| POST | /api/chat | DeepSeek 对话（真实大模型） |
| POST | /api/rag/ingest | 写入文献片段到向量库 |
| POST | /api/rag/search | 语义检索相关文献 |
