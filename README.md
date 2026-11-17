# 智汇研途 - 可核验的科研对话助手

传智杯 AI 大模型创新应用挑战赛参赛作品。

## 参赛信息

| 项目 | 内容 |
| ---- | ---- |
| 赛事 | 第九届传智杯全国大学生数智创新与 AI 应用大赛 · AI 大模型创新应用挑战赛 |
| 参赛形式 | 个人赛 |
| 参赛者 | 刘露嘉 |
| 学校 | 天津商务职业学院 |
| 指导教师 | 武臻 |

## 在线演示

| 项目 | 内容 |
| ---- | ---- |
| 演示地址 | <http://139.224.206.77:8000> |
| 评审账号 | `demo` / `demo123456` |
| 健康检查 | <http://139.224.206.77:8000/api/health> |

> 演示环境为 Docker 单容器部署，评审期间保持在线。

> **AI 辅助开发声明**：本项目使用 DeepSeek 作为 AI 辅助开发工具，用于生成代码骨架、页面布局与基础逻辑；所有代码均经过人工审核、调试与修改，关键逻辑（API 调用、边界处理、错误重试）由人工确认，确保可稳定运行。

## 项目简介

智汇研途是一个**可核验的科研对话助手**：把文献检索、引用核验、学术翻译、术语速查、跨文献对比、综述生成、文档问答等 17 项能力收进同一个对话框，用户用自然语言提需求，系统自动路由并编排。

与通用对话产品最大的区别是**严谨性门控**：任何文献、译名、译文都必须先通过至少 2 条彼此独立的通道复核，答案一致才进入结论区；不一致或无法复核的条目移入「未通过核验」区并公示，绝不降级为模型自由作答。

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

## 部署到服务器（在线演示）

比赛要求提供「**可公网访问**的在线演示地址」，且**评审期间须保持服务可用**。项目已内置 Docker 配置，推荐用 **Oracle Cloud 永久免费主机**（ARM 4 核 24G，免费额度足够），x86_64 / ARM64 均可。

📖 完整步骤见 **[docs/部署指南.md](docs/部署指南.md)**（含注册、放行端口、对象存储备份、域名 HTTPS）。

> 💳 **没有信用卡？** Oracle 注册必须验证真实信用卡。替代方案见部署指南 **0.5 节**：
> ① 阿里云高校计划（学生认证送 300 元券，券后 0 元，支付宝即可，选**海外**地域）
> ② 本机 + Cloudflare 隧道（`scripts/public-demo/start-tunnel.bat`，0 元 0 注册，应急演示）

### 方式一：一键脚本（推荐，Oracle / 任意 Ubuntu）

```bash
git clone <仓库地址> zhihui && cd zhihui
bash scripts/oracle/bootstrap.sh     # 装 Docker、建 swap、放行 80/443/8000
cp .env.example .env && nano .env    # 填入 DEEPSEEK_API_KEY
bash scripts/oracle/deploy.sh        # 构建 + 启动 + 健康检查 + 演示账号
PORT=80 bash scripts/oracle/deploy.sh # 想让地址不带 :8000 就用这句
```

### 方式二：手动 Docker Compose

```bash
git clone <仓库地址> zhihui && cd zhihui
cp .env.example .env                 # 填入 DEEPSEEK_API_KEY
docker compose up -d --build
docker compose exec zhihui python /app/scripts/init_demo_user.py   # 评审专用账号
```

启动后访问 `http://<服务器IP>:8000`。

> 前端会自动探测后端地址（同源优先），**服务器部署无需任何额外配置**；本地双击 `index.html` 打开时才回落到 `127.0.0.1:8000`。

### 方式三：直接运行（无 Docker）

```bash
pip install -r requirements.txt
export ZHIHUI_DATA_DIR=/opt/zhihui-data      # Windows: set ZHIHUI_DATA_DIR=D:\zhihui-data
uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir backend
```

### 数据备份到 Oracle 对象存储

```bash
bash scripts/oracle/setup-rclone-oci.sh   # 配置 rclone 连接 OCI（一次性）
bash scripts/oracle/backup-to-oci.sh      # 备份 /data 到存储桶
bash scripts/oracle/restore-from-oci.sh   # 灾难恢复
```

配合 crontab 每天自动备份，命令见部署指南第 8 节。

### 环境变量

| 变量 | 必填 | 说明 |
| ---- | ---- | ---- |
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek API 密钥（见 `platform.deepseek.com`）|
| `ZHIHUI_DATA_DIR` | | 用户数据目录。默认 `~/zhihui-data`，Docker 内为 `/data` |
| `ZHIHUI_FRONTEND_DIR` | | 前端目录。默认自动定位仓库中的 `frontend/` |
| `ZHIHUI_PORT` | | compose 对外端口，默认 `8000` |
| `PIP_INDEX_URL` | | 构建期 pip 镜像源，国内建议换清华源 |

完整模板见仓库根目录 `.env.example`。

### 健康检查

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok","service":"zhihui-yantu","version":"2.0",...}
```

### 评审演示账号

```bash
python scripts/init_demo_user.py                        # demo / demo123456
python scripts/init_demo_user.py --username judge --password 'xxx' --admin
```

脚本可重复执行；账号已存在时会重置密码。

### 部署注意事项

- **建议使用 HTTPS**：浏览器 Web Crypto API（AES 加密归档）仅在安全上下文可用，`http://公网IP` 下会失效。推荐绑定域名 + Let's Encrypt 证书，或由云厂商提供 HTTPS 反向代理。
- **数据持久化**：Docker 使用命名卷 `zhihui-data`，`docker compose down` 不丢数据；执行 `docker compose down -v` 才会清空。
- **端口与防火墙**：Oracle / 阿里云等需**两处**放行——云控制台安全列表 + 主机内部 iptables（Oracle 的 Ubuntu 镜像默认拒绝 22 以外入站）。`scripts/oracle/bootstrap.sh` 已自动处理主机侧，控制台仍需手动加规则。
- **免费机型**：Oracle Always Free 的 ARM A1（2026 年上限 2 OCPU / 12 GB，早期账号为 4 / 24）最合适；1 GB 的 E2.1.Micro 也能跑，但首次构建慢，脚本会自动创建 2 GB swap。配额以创建页「Always Free-eligible」标签为准。
- **API 费用**：DeepSeek 按量计费，公开演示建议在控制台设置额度上限，防止被刷。

## 主要接口一览（67 个）

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

## 用户数据与隐私（本地优先）

### 数据目录（按使用者隔离）
每个使用者拥有独立的个人目录，互不可见。目录默认位于用户主目录下的 `zhihui-data`（Windows 为 `C:\Users\<用户名>\zhihui-data`），可通过环境变量 `ZHIHUI_DATA_DIR` 指定到任意位置（如服务器上的 `/data`）。

```
<数据目录>\
├── users.db                 # SQLite：历史 / 团队 / 课题 / 对话 / 记录（按 username 隔离）
├── consent.json             # 全局目录授权记录
└── users\
    ├── testuser\            # 使用者 A 的个人目录
    │   ├── consent.json     # 该使用者的授权记录
    │   ├── profile.json     # 个人资料
    │   ├── history.json     # 浏览历史
    │   ├── teams.json       # 所属团队
    │   └── docs.json        # 团队文档
    └── alice\               # 使用者 B 的个人目录
        └── ...
```

### 授权机制（每个使用者独立）
- **每个使用者首次使用时**都会弹出授权对话框，说明目录位置与用途
- **本人点「同意并创建」后**才创建其个人目录并导出数据
- 点「拒绝」则该使用者不创建目录，仅使用临时存储
- 可在「隐私与数据」面板随时**撤销本人的授权**

### 使用者权限（RBAC）
| 角色 | 权限 |
|------|------|
| **管理员（admin）** | 查看全部使用者、调整角色、删除他人数据 |
| **普通使用者（member）** | 仅能查看/管理自己的数据 |

- **首个授权使用者自动成为管理员**
- 越权访问管理接口返回 `403`
- 管理员可在面板中把使用者「设为管理员 / 降为成员」

### 权限收紧
创建目录时自动执行 ACL 收紧，仅保留：

| 账户 | 权限 |
|------|------|
| 当前用户 | 完全控制 |
| SYSTEM | 完全控制 |
| Administrators | 完全控制 |

移除了 `Everyone` / `Users` 继承权限，**同机其他 Windows 用户无法访问**。

### 三层隐私保护

| 层级 | 措施 | 效果 |
|------|------|------|
| **存储加密** | 前端 `AES-256-GCM` + `PBKDF2-SHA256(120000)` 加密归档 | 磁盘只留密文 `data.enc`，明文 JSON 立即删除；无密码无法还原 |
| **隐私模式** | 一键切断所有云端调用 | 问答/翻译/润色/检索等 16 个联网接口全部拦截，纯本地运行 |
| **最小化留存** | 一键清理 30 天前历史 | 减少长期留存风险 |

加密密钥**只在浏览器内由密码派生**，不上传服务器；服务端只保存密文。

### 浏览器端数据
账号密码以 SHA-256 哈希保存在浏览器 `localStorage`，不发送服务器；「隐私与数据」面板支持一键清空。

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
