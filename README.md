## 项目名称
基于 GraphRAG 的风机知识图谱构建与问答系统

## 项目用途
本项目为本科毕业设计原型系统，面向风机运维场景，完成从标准文档/PDF数据到知识图谱构建，再到问答与证据展示的完整流程。系统核心能力为：

- 离线知识构建：PDF处理、文本清洗、切块、实体关系抽取、Neo4j建图
- 在线问答展示：实体查询、规则问答、GraphRAG问答（LLM增强 + 模板兜底）
- 证据可追溯：答案可回溯至来源文件、关系句和页码信息

---

## 环境准备

### 1) Python 版本建议
- 建议使用 `Python 3.10` 或 `Python 3.11`
- 建议先创建虚拟环境后安装依赖

示例（Windows PowerShell）：
```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2) Neo4j 准备
- 建议使用 `Neo4j 5.x`
- 启动本地 Neo4j 服务后，确认可访问 `neo4j://127.0.0.1:7687`
- 在 `app/config.py` 中配置：
  - `NEO4J_URI`
  - `NEO4J_USER`
  - `NEO4J_PASSWORD`

### 3) 依赖安装
- 项目依赖统一在根目录 `requirements.txt`
- 直接执行：
```bash
pip install -r requirements.txt
```

### 4) OCR 依赖说明（可选）
- 仅当需要处理**扫描型 PDF**时，才需要完整 OCR 链路
- OCR核心依赖为 `paddleocr` 与 `paddlepaddle`，建议按 `requirements.txt` 中版本安装
- 若只做系统页面演示（已有抽取与建图结果），可不重新执行 OCR 脚本

---

## 项目目录说明

- `app/`：Flask Web 应用与问答逻辑
  - `app.py`：应用入口与路由
  - `config.py`：统一配置入口（Neo4j、LLM、数据目录）
  - `db.py`：Neo4j连接与查询封装
  - `graph_rag.py`：GraphRAG主流程
  - `services/`：图查询、规则问答、LLM调用服务
  - `templates/`：前端页面模板
- `scripts/`：离线主链路脚本（数据处理与建图）
- `scripts/legacy/`：历史版本/调试脚本归档（不参与最终主链路）
- `meta/`：实体关系抽取结果与过程清单（如 `entities_v3_1.jsonl`、`relations_v3_1.jsonl`）
- `chunks/`：文档切块结果
- `merged_text/`：清洗后合并文档结果
- `raw_pdf/`：原始PDF输入目录
- `extracted_text/`、`cleaned_text/`：中间文本产物
- `data/`：本项目数据工作区根（即当前仓库根目录所处工作区）

---

## 最简启动流程（完整重跑版）

适用场景：需要从原始文档重新处理、重新抽取并重建图谱。

### 步骤 1：安装依赖
```bash
pip install -r requirements.txt
```

### 步骤 2：配置 Neo4j 与系统参数
编辑 `app/config.py`，至少确认：
- Neo4j连接信息（`NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`）
- 路径配置（`BASE_DIR`、`META_DIR`、`CHUNKS_DIR` 等）

### 步骤 3：准备数据
- 将原始 PDF 放入 `raw_pdf/`
- 若已有 `meta/pdf_inventory.csv`，可按需覆盖或复用

### 步骤 4：按脚本顺序执行离线链路
```bash
python scripts/scan_pdfs.py
python scripts/detect_pdf_type.py
python scripts/extract_text.py
python scripts/ocr_extract_pdf.py
python scripts/clean_text.py
python scripts/clean_ocr.py
python scripts/merge_cleaned_text_sources.py
python scripts/chunk_merged_docs.py
python scripts/extract_entities_relations_v3_1.py
python scripts/build_graph_v3_1.py
```

### 步骤 5：启动 Flask 前端
```bash
cd app
python app.py
```
浏览器访问：`http://127.0.0.1:5000/`

---

## 仅演示系统页面时的启动方式（不重跑抽取/建图）

适用场景：答辩演示、已有历史产物，不希望重新跑离线脚本。

前提：
- Neo4j 中已有图数据（已建图完成）
- `app/config.py` 中 Neo4j 配置正确

启动方式：
```bash
cd app
python app.py
```
然后直接访问页面：
- `/entity`：实体查询
- `/qa`：规则问答
- `/graph_rag`：GraphRAG问答

---

## 配置说明（`app/config.py`）

### Neo4j 配置
- `NEO4J_URI`：数据库地址
- `NEO4J_USER` / `NEO4J_PASSWORD`：账号密码

### 数据目录配置
- `BASE_DIR`：项目根目录
- `META_DIR`、`CHUNKS_DIR`、`RAW_PDF_DIR`
- `EXTRACTED_TEXT_DIR`、`CLEANED_TEXT_DIR`
- `MERGED_TEXT_DIR`、`MERGED_DOCS_DIR`
- `ENTITIES_FILE`、`RELATIONS_FILE`

### LLM 配置（GraphRAG增强）
- `LLM_ENABLED`：是否启用LLM增强（提交版建议默认 `False`）
- `LLM_API_KEY`：API密钥（提交仓库不要放真实密钥）
- `LLM_BASE_URL`：只配置到 `/v1`
- `LLM_MODEL_NAME`：模型名
- `LLM_TIMEOUT`：请求超时秒数

说明：当 `LLM_ENABLED=False` 或接口不可用时，系统自动回退模板答案，不影响基本演示。

---

## 常见问题（FAQ）

### 1) Neo4j 连接失败怎么办？
- 检查 Neo4j 服务是否已启动
- 检查 `app/config.py` 中 `NEO4J_URI/USER/PASSWORD` 是否正确
- 确认本机端口 `7687` 可访问
- 可先在 Neo4j Browser 验证登录再启动 Flask

### 2) `meta/relations_v3_1.jsonl` 不存在怎么办？
- 说明实体关系抽取步骤未完成
- 先执行：
  - `python scripts/chunk_merged_docs.py`
  - `python scripts/extract_entities_relations_v3_1.py`
- 再执行 `python scripts/build_graph_v3_1.py`

### 3) OCR 环境报错怎么办？
- 确认已安装 `paddleocr` 与 `paddlepaddle`
- 建议使用 `requirements.txt` 指定版本
- 在 Windows 下优先使用 CPU 版本环境，避免 CUDA 依赖不一致
- 若仅答辩演示且已有图数据，可跳过 OCR 相关脚本

### 4) 页面显示“未知页码”怎么办？
- 检查关系数据中是否有 `page_num/page_span`
- 确认已使用当前版本 `scripts/build_graph_v3_1.py` 重建图数据库
- 确认 Neo4j 中关系属性已写入页码字段

---

## 说明
- 本仓库 `scripts/` 根目录为最终主链路脚本；`scripts/legacy/` 仅用于历史追溯，不作为最终提交运行流程。
- 本系统用于毕业设计展示与研究验证，问答结果需以图谱与文本证据为准。
