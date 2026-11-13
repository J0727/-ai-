# 智汇研途 - AI科研辅助平台

传智杯 AI 大模型创新应用挑战赛参赛作品。

> **AI 辅助开发声明**：本项目使用 DeepSeek 作为 AI 辅助开发工具，用于生成代码骨架、页面布局与基础逻辑；所有代码均经过人工审核、调试与修改，关键逻辑（API 调用、边界处理、错误重试）由人工确认，确保可稳定运行。

## 项目简介

智汇研途是一个基于**多智能体协作**与 **RAG 检索增强**的科研辅助平台，覆盖「文献导入 → 问答溯源 → 引用图谱 → 综述生成 → 学科检索 → 相似度自查 → 团队协作」的完整科研工作流。

## 核心功能

### 文献处理
- **PDF 文献导入**：支持标准文本 PDF 与扫描件（自动 OCR）
- **抗幻觉 RAG**：基于 ChromaDB 的语义检索，先查文献再生成
- **问答溯源**：回答附带参考来源（文件 + 片段号），结论可核验
- **引用图谱**：基于相似度构建文献关系网络，挖掘「基石节点」
- **PDF 版式阅读**：浏览器原生渲染，保留原始排版

### 学术写作
- **文献综述 / 论文大纲**：基于已上传文献一键生成
- **学术润色**：纠错 + 术语规范化 + 修改点清单
- **文献纠错**：Crossref 真实库校验，支持替换 / 自定义 / 不替换
- **CSV 数据可视化**：CSV → 图表；CSV → LaTeX 表格

### 多语言
- **学术翻译**：20 种主流语言互译
- **界面多语言**：中/英/日/韩/西/法/德/俄/阿 9 种界面语言
- **文献语言插件**：文献标题与正文翻译为 20 种语言

### 学科与检索
- **学科资料库**：12 个主学科 × 92 个子领域，两级分类
- **多源文献检索**：OpenAlex / arXiv / Europe PMC / DOAJ / Zenodo / Crossref / OpenAIRE / PubMed 八源并行
- **文献库自由搜索**：支持标题、作者、文献片段
- **全文与引用**：完整正文提取、GB/T 7714 / APA / MLA / BibTeX 引用生成
- **AI 课题分类**：新建课题时自动匹配学科与子领域

### 用户与协作
- **注册 / 登录**：SQLite 持久化，密码 SHA-256 哈希
- **浏览历史**：绑定账号，精确到具体文章，可编辑/删除
- **文献相似度自查**：8 源并行比对，支持整篇论文（最高 10 万字），段落级高风险定位（相似度参考，非商业查重）
- **团队协作**：团队代码、邀请权限（只读/可编辑）、文档在线编辑

## 技术栈

- 前端：HTML + TailwindCSS + Font Awesome + Chart.js
- 后端：FastAPI + ChromaDB + pypdf + PyMuPDF + RapidOCR + SQLite
- 模型：DeepSeek Chat API

## 目录结构

```
.
├── README.md
├── requirements.txt
├── .gitignore
├── frontend/
│   └── index.html            # 前端界面（工具箱 11 项核心功能）
├── backend/
│   ├── main.py               # FastAPI 后端（40+ 个接口）
│   ├── .env.example          # 环境变量示例
│   └── 启动后端.bat           # 一键启动脚本（Windows）
└── docs/
    ├── 系统设计报告.docx / .pdf   # 概要设计 + 详细设计（含架构图）
    ├── 技术文档.docx / .pdf
    ├── 作品介绍文档.docx / .pdf
    ├── design/                    # 设计图（架构图 / 模块图 / 数据流图）
    ├── 演示视频脚本-最终版.md
    ├── 技术报告大纲.md
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

## 主要接口一览（36 个）

### 基础与 RAG
| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | /health | 健康检查 |
| POST | /api/chat | DeepSeek 对话（含 RAG 上下文与来源） |
| POST | /api/rag/ingest | 写入文献片段 |
| POST | /api/rag/search | 语义检索 |
| POST | /api/upload | 上传 PDF（文本 + OCR） |
| POST | /api/extract-text | 提取 PDF/TXT 纯文本 |

### 写作与可视化
| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | /api/writing | 生成论文大纲 |
| POST | /api/survey | 生成文献综述 |
| POST | /api/polish | 学术润色 |
| POST | /api/translate | 多语言翻译（20 种） |
| GET | /api/languages | 支持语言列表 |
| POST | /api/translate-batch | 批量翻译（界面/文献） |
| POST | /api/visualize | CSV → 图表数据 |
| POST | /api/latex | CSV → LaTeX 表格 |

### 文献与检索
| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | /api/graph | 引用图谱 + 基石节点 |
| GET | /api/arxiv | arXiv 检索（离线兜底） |
| POST | /api/literature-search | 多源并行文献检索 |
| POST | /api/library-search | 文献库自由搜索（标题/作者/片段） |
| POST | /api/verify-citation | Crossref 文献引用校验 |
| POST | /api/article-detail | 文献完整内容（含 arXiv 全文） |
| POST | /api/plagiarism-check | 文献相似度自查（8 源，最高 10 万字） |

### 学科与分类
| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | /api/subjects | 学科树（12 主 × 92 子） |
| GET | /api/subjects/{id}/literature | 按学科/子领域检索文献 |
| POST | /api/classify-topic | AI 课题分类建议 |

### 用户与历史
| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | /api/register | 用户注册 |
| POST | /api/login | 用户登录 |
| GET | /api/users | 用户资料库 |
| POST | /api/history | 记录浏览历史 |
| GET | /api/history | 查询浏览历史 |
| PUT | /api/history/{id} | 修改历史备注 |
| DELETE | /api/history/{id} | 删除历史记录 |

### 团队协作
| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | /api/teams | 创建团队（生成团队代码） |
| POST | /api/teams/join | 用代码加入团队 |
| POST | /api/teams/invite | 邀请成员（指定权限） |
| GET | /api/teams/mine | 我的团队列表 |
| GET | /api/teams/{code} | 团队详情（成员 + 文档） |
| POST | /api/teams/{code}/docs | 新建文档 |
| GET | /api/teams/{code}/docs/{id} | 读取文档 |
| PUT | /api/teams/{code}/docs/{id} | 保存文档 |
| DELETE | /api/teams/{code}/docs/{id} | 删除文档 |

## 免责声明与合规说明

> 本项目仅用于**学术研究辅助**与**教学演示**，不用于商业用途。

### 文献数据来源
本项目的文献检索与相似度自查功能，均通过以下**公开学术 API** 获取数据：

| 数据源 | 说明 | 授权/条款 |
| ------ | ---- | --------- |
| [OpenAlex](https://openalex.org/) | 开放学术知识图谱 | CC0 公有领域 |
| [Crossref](https://www.crossref.org/) | 全球 DOI 注册中心 | 免费，需带 User-Agent |
| [arXiv](https://arxiv.org/) | 预印本论文库 | 遵循 arXiv API 使用条款 |
| [Europe PMC](https://europepmc.org/) | 生命科学文献库 | 开放获取 |
| [DOAJ](https://doaj.org/) | 开放获取期刊目录 | 开放获取 |
| [Zenodo](https://zenodo.org/) | 开放科研仓库（CERN） | 开放获取 |
| [OpenAIRE](https://www.openaire.eu/) | 欧洲开放科学平台 | 开放获取 |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov/) | 美国国立医学图书馆 | 开放获取 |

**本项目的使用方式**：
- ✅ 仅调用官方公开 API，遵守各平台的速率限制
- ✅ 仅展示标题、作者、年份、DOI、摘要等公开元数据
- ✅ 全文仅在请求时临时提取，**不存储、不分发、不对外提供下载**
- ✅ 所有文献均提供原文链接（DOI / arXiv），引导用户访问原始出处

### 版权声明
- 所有文献的**著作权归原作者及出版机构所有**
- 本项目不主张对任何文献内容的权利
- 相似度自查结果仅为**相似度参考**，不构成侵权判定依据
- 翻译内容仅为个人学习辅助，如涉及传播需获得原作者授权

### 知识产权
- 本项目的代码与界面设计归参赛团队所有
- 使用第三方开源库遵循其各自的许可证（FastAPI、ChromaDB、PyMuPDF 等）

### 使用建议
如将本项目用于**商业用途或公开部署**，请：
1. 自行确认各 API 的商用条款
2. 移除或限制全文提取功能
3. 增加用户协议与隐私政策
4. 咨询专业法律意见

## 致谢

感谢 DeepSeek 提供的模型能力，感谢 OpenAlex、Crossref、arXiv、Europe PMC、DOAJ、Zenodo、OpenAIRE、PubMed 等开放学术平台提供的公共数据接口。
