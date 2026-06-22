from pathlib import Path

NEO4J_URI = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "12345678"   # 改成你自己的密码

APP_HOST = "127.0.0.1"
APP_PORT = 5000
DEBUG = True

# ========= 项目路径配置（统一入口） =========
# 以项目根目录为基准：<repo_root>/app/config.py -> <repo_root>
BASE_DIR = Path(__file__).resolve().parent.parent
META_DIR = BASE_DIR / "meta"
CHUNKS_DIR = BASE_DIR / "chunks"
RAW_PDF_DIR = BASE_DIR / "raw_pdf"
EXTRACTED_TEXT_DIR = BASE_DIR / "extracted_text"
OCR_EXTRACTED_DIR = EXTRACTED_TEXT_DIR / "ocr_pdf"
CLEANED_TEXT_DIR = BASE_DIR / "cleaned_text"
OCR_CLEANED_DIR = CLEANED_TEXT_DIR / "ocr_pdf"
MERGED_TEXT_DIR = BASE_DIR / "merged_text"
MERGED_DOCS_DIR = MERGED_TEXT_DIR / "docs"
FAILED_DIR = BASE_DIR / "failed"
PDF_INVENTORY_CSV = META_DIR / "pdf_inventory.csv"
ENTITIES_FILE = META_DIR / "entities_v3_1.jsonl"
RELATIONS_FILE = META_DIR / "relations_v3_1.jsonl"

# ========= LLM / GraphRAG 增强配置 =========
# 提交/答辩版建议默认关闭；需要演示时再手动开启并填写 API Key
LLM_ENABLED = True
# 出于安全原因，请勿在代码仓库中提交真实 API Key
LLM_API_KEY = "sk-90c8bd039dca487386b01a60a9b5cc79"
# 只需要配置到 /v1，代码中会自动拼接 /chat/completions
LLM_BASE_URL = "https://api.deepseek.com/v1"
LLM_MODEL_NAME = "deepseek-chat"
LLM_TIMEOUT = 15