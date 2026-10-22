# ResearchOS — 多文档 AI 研究工作台

一个证据驱动的多文档研究平台（类似 NotebookLM）：上传多份文档后，进行混合检索、带可核验引用的问答、跨文档比较（区分真正矛盾 / 时间变化 / 适用条件 / 补充信息）和 Markdown 研究报告生成。

重点在于文档处理、检索质量、引用准确性和可验证的工作流，而不是聊天界面。

## 빠른 시작 (Docker, API 키 불필요)

준비물은 [Docker Desktop](https://www.docker.com/products/docker-desktop/)(Windows / macOS) 또는 Docker Engine(Linux) 하나뿐입니다.

```bash
git clone https://github.com/nimgnus21/ResearchOS.git
cd ResearchOS
docker compose up -d --build
```

첫 실행은 이미지를 받고 빌드하느라 몇 분 걸립니다. 끝나면 브라우저에서 **http://localhost:3000** 을 엽니다.

- 중지: `docker compose down` (업로드한 문서와 DB는 Docker 볼륨에 남습니다)
- 데이터까지 모두 삭제: `docker compose down -v`
- 로그 보기: `docker compose logs -f backend`
- 3000 / 8000 포트를 다른 프로그램이 쓰고 있으면 `docker-compose.yml`의 `ports`를 바꿉니다 (예: `"3001:3000"`).

API 키 없이 동작하는 것: 업로드·파싱, 하이브리드 검색, 질문에 대한 원문 근거 제시(문서·페이지·하이라이트), 근거 부족 시 거절, 문서별 근거 비교, 근거 모음 보고서 작성·편집·다운로드.
API 키가 필요한 것: 모델이 작성하는 결론 문장, 비교의 A/B/C/D 분류, 보고서 요약. 나중에 키가 생기면 `backend/.env`에 `LLM_PROVIDER` / `LLM_API_KEY`를 넣고 `docker compose up -d --build backend`.

## 当前状态（如实说明）

| 能力 | 状态 |
|---|---|
| 项目管理、上传、解析（PDF/DOCX/TXT/MD）、分块、索引、去重、重试、删除清理 | ✅ 可用，有测试 |
| 混合检索（PostgreSQL 全文 + pgvector）、RRF 融合、过滤、阈值、检索日志 | ✅ 可用，有测试 |
| 问答 / 比较 / 报告的**检索与证据部分**、引用定位到文档+页码+原文 | ✅ 可用，有测试 |
| 问答 / 比较 / 报告的**模型生成部分** | ⚠️ 代码完整，引用校验逻辑已用测试替身（scripted test double）测试；**尚未在真实 API 上运行过**（开发环境没有 API 密钥） |
| 默认向量模型 | ⚠️ 离线“哈希词法向量”，不是神经语义模型；可切换为 OpenAI 兼容的 Embedding 接口 |
| OCR | ❌ 未实现：扫描件会被识别并标记为“需要 OCR” |

未配置模型时，系统**不会伪造回答**：问答返回 `llm_unavailable` 并列出检索到的原文证据；比较返回逐文档证据矩阵；报告生成“证据汇编”草稿（摘要处标注待人工撰写）。

## 目录结构

```
backend/                FastAPI + SQLAlchemy + Alembic
  app/
    api/routes.py       全部 REST 接口（所有子资源都按 project_id 限定）
    api/deps.py         项目范围内的资源查找（跨项目 → 404）
    services/
      parsing.py        PDF(PyMuPDF) / DOCX(python-docx) / TXT / MD 解析，保留页码、标题、元数据
      chunking.py       结构感知分块（句子级重叠、不跨页、偏移量可精确回溯原文）
      text_utils.py     中英文分词（CJK 二元组 + 停用词切分）
      embeddings.py     Embedding 抽象：hash（离线）/ openai 兼容
      llm.py            LLM 抽象：anthropic（官方 SDK，结构化输出）/ openai 兼容 / none
      ingestion.py      处理管线：校验→哈希去重→存储→解析→分块→向量化→入库；原子领取任务
      retrieval.py      混合检索、RRF 融合、IDF 加权词项覆盖率、证据阈值、检索日志
      evidence.py       证据渲染（防注入定界）与模型引用校验
      qa.py / compare.py / report.py
  alembic/versions/     数据库迁移（主外键、复合外键、唯一约束、索引）
  tests/                pytest（66 个）
frontend/               Next.js 16 + TypeScript + Tailwind v4
  app/page.tsx          三栏工作台（移动端为三个切换面板）
  components/           项目/文档库、问答、检索、比较、报告、证据面板
  e2e/                  Playwright 端到端测试
eval/
  corpus/build_corpus.py   生成虚构测试语料（KX-200 泵轴承过热）
  questions.json           固定评估问题（可回答 / 不可回答 / 比较）
  run_eval.py              评估运行器 → eval/results/eval_report.{md,json}
scripts/dev.sh, stop.sh    一键启动 / 停止（非 Docker）
docker-compose.yml         Docker 一键运行（db + backend + frontend）
```

## 运行环境与安装

需要：Python 3.11+、Node 20+、PostgreSQL 15+（使用了 `ON DELETE SET NULL (列)` 语法）、pgvector。

```bash
# PostgreSQL + pgvector（Ubuntu/Debian 示例）
sudo apt-get install -y postgresql-16 postgresql-16-pgvector
sudo service postgresql start
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"
sudo -u postgres createdb researchos
sudo -u postgres createdb researchos_test     # pytest 使用
sudo -u postgres createdb researchos_eval     # 评估使用

# 后端
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # 按需配置模型密钥
.venv/bin/alembic upgrade head

# 前端
cd ../frontend && npm install
```

## 启动

```bash
scripts/dev.sh      # 迁移数据库，启动后端 :8000 与前端 :3000（首次会构建前端）
scripts/stop.sh
```

或分别启动：

```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000
cd frontend && npm run dev          # 浏览器访问 http://localhost:3000
```

前端通过 Next.js rewrites 把 `/api/*` 代理到 `BACKEND_URL`（默认 `http://127.0.0.1:8000`）。

## 配置模型

在 `backend/.env` 中设置（见 `.env.example`）。密钥只从环境变量读取，日志中会被屏蔽。

```bash
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
LLM_MODEL=claude-opus-5-5
```

Anthropic 调用使用官方 `anthropic` SDK：流式请求、自适应思考、`output_config.format` JSON Schema 结构化输出，默认开启服务端拒答回退（`LLM_FALLBACKS=default`，可设为 `off`）。也支持任意 OpenAI 兼容接口（`LLM_PROVIDER=openai` + `LLM_BASE_URL`）。

切换 Embedding（例如 `EMBEDDING_PROVIDER=openai`）后需要对已有文档点击“重试”或重新上传，因为向量按模型名标记，不同模型的向量不会混用。

## 关键设计

**项目隔离**：每个子表都带 `project_id`，并通过复合外键 `(id, project_id)` 引用父表，数据库层面保证分块不可能属于另一项目的文档、引用不可能指向另一项目的分块。所有 API 均以 `(资源 id, URL 中的 project_id)` 双条件查询，跨项目访问返回 404。

**页码可追踪**：PDF 使用物理页；DOCX 按显式分页符（或 Word 渲染分页）划分逻辑页，无分页时记为第 1 页并给出提示；TXT/MD 支持换页符分页，并为每个分块记录行号。分块不跨页，分块文本严格等于 `page.text[char_start:char_end]`，因此引用可以在原页文本中精确高亮。

**混合检索**：关键词检索用 PostgreSQL `tsvector`（Python 端预分词，CJK 用二元组），向量检索用 pgvector 余弦距离，两路结果用 RRF 融合并按分块去重、按文档内相同文本去重。每个结果返回 `document_id / document_name / page_number / chunk_id / 原文 / relevance`（两路排名、相似度、覆盖率、是否达标）。

**证据阈值不只看向量相似度**：分块要么覆盖足够比例的查询词项（按项目内 IDF 加权，避免“KX-200”这类处处出现的词撑起覆盖率），要么向量相似度很高，才算证据。阈值可配置，并随每次检索记录到 `retrieval_runs`。

**引用校验**：模型只能引用本次检索提供的证据编号；系统会移除不存在的编号、逐字核对引文（不一致则不显示该引文）、把没有有效引用的“事实”降级为“未经证实”，并据此下调回答状态。报告的引用来源清单由系统根据真实检索结果生成，不由模型书写。

**提示注入**：文档内容放在 `<evidence>` 定界块中（并转义闭合标签），系统提示明确规定其中内容只是待分析材料。测试语料中包含一条注入指令用于验证定界。

**删除**：删除文档会级联删除页、分块和向量并删除存储目录；历史引用保留快照（文档名、页码、引文），并标注“源文档已删除”。

**处理任务**：上传后后台线程池处理；任务通过原子更新领取，多实例不会重复处理；超时（默认 30 分钟）的“处理中”任务在启动时被回收重排。

## 测试

```bash
cd backend && .venv/bin/pytest -q                    # 66 个测试，使用 researchos_test 数据库

# 端到端（需先 scripts/dev.sh 启动应用）
cd frontend && npx playwright test
# 沙箱/离线环境可指定已安装的 Chromium：
PW_CHROMIUM_PATH=/path/to/chrome npx playwright test

# 检索/引用评估（固定问题集，结果写入 eval/results/）
backend/.venv/bin/python eval/run_eval.py
```

pytest 覆盖：PDF/DOCX/TXT/MD 解析、页码与引用映射、空文件与损坏文件、加密 PDF、扫描件、分块与元数据、混合检索合并去重与过滤、跨项目隔离（API + 数据库约束）、无证据拒答且不调用模型、模型引用校验（无效编号/篡改引文/无依据陈述）、提示注入定界、删除后索引清理、不存在的引用 ID、报告生成/编辑/导出、重复检测、重试、任务领取与回收、长页面窗口化。

评估报告见 `eval/results/eval_report.md`。注意：语料与问题由开发者编写，检索规则曾针对评估中暴露的问题修正，指标偏乐观。

## 已知限制

- 未实现 OCR；扫描件只会被识别和提示。
- 默认哈希词法向量没有语义/跨语言能力（中文问题检索不到只用英文写成的同义内容）；生产使用请配置真实 Embedding。
- 模型生成路径尚未用真实 API 运行验证。
- 无用户认证：项目是唯一的权限边界，适合单用户/可信网络部署。
- 大文件处理在单进程线程池中进行，没有独立任务队列（实测 35 MB 纯文本 → 30,481 个分块，处理约 56 秒）。
- 向量检索为项目内精确扫描（未建 ANN 索引）：3 万分块时单次检索约 0.6–1.3 秒。
