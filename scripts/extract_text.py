from pathlib import Path
import pandas as pd
from tqdm import tqdm
import fitz
import json
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import config

# ========= 1. 路径配置 =========
INVENTORY_CSV = config.PDF_INVENTORY_CSV
OUTPUT_DIR = config.EXTRACTED_TEXT_DIR
FAILED_DIR = config.FAILED_DIR

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FAILED_DIR.mkdir(parents=True, exist_ok=True)

# ========= 2. 读取清单 =========
df = pd.read_csv(INVENTORY_CSV)

# 只提取“疑似文本型 PDF”
text_df = df[df["is_scanned_suspect"] == False].copy()

# ========= 3. 初始化状态列 =========
if "extract_status" not in df.columns:
    df["extract_status"] = None
if "output_json" not in df.columns:
    df["output_json"] = None

# ========= 4. 工具函数 =========
def safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", str(name))
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180]

def extract_pdf_text(pdf_path_str):
    pdf_path = Path(pdf_path_str)
    doc = fitz.open(pdf_path)

    pages = []
    full_text_parts = []

    for i, page in enumerate(doc):
        text = page.get_text("text")
        text = text if text else ""
        pages.append({
            "page_num": i + 1,
            "text": text
        })
        if text.strip():
            full_text_parts.append(text)

    full_text = "\n".join(full_text_parts).strip()
    return pages, full_text

# ========= 5. 批量提取 =========
for idx, row in tqdm(text_df.iterrows(), total=len(text_df), desc="提取文本型PDF"):
    if pd.notna(df.at[idx, "extract_status"]) and str(df.at[idx, "extract_status"]).startswith("success"):
        continue

    try:
        file_stem = safe_name(row["file_stem"])
        rel_path = Path(row["relative_path"])

        # 按原目录层级输出，便于后续管理
        subdirs = rel_path.parts[:-1]
        out_subdir = OUTPUT_DIR.joinpath(*subdirs)
        out_subdir.mkdir(parents=True, exist_ok=True)

        out_json_path = out_subdir / f"{file_stem}.json"

        pages, full_text = extract_pdf_text(row["full_path"])

        data = {
            "file_stem": row["file_stem"],
            "file_name": row["file_name"],
            "full_path": row["full_path"],
            "relative_path": row["relative_path"],
            "level_1_dir": row.get("level_1_dir", ""),
            "level_2_dir": row.get("level_2_dir", ""),
            "level_3_dir": row.get("level_3_dir", ""),
            "page_count": int(row["page_count"]) if pd.notna(row["page_count"]) else len(pages),
            "pages": pages,
            "full_text": full_text
        }

        with open(out_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        df.at[idx, "extract_status"] = "success"
        df.at[idx, "output_json"] = str(out_json_path)

    except Exception as e:
        df.at[idx, "extract_status"] = f"failed: {str(e)[:100]}"
        df.at[idx, "output_json"] = ""

# ========= 6. 保存更新后的清单 =========
df.to_csv(INVENTORY_CSV, index=False, encoding="utf-8-sig")

# ========= 7. 输出统计 =========
success_count = df["extract_status"].astype(str).str.startswith("success").sum()
failed_count = df["extract_status"].astype(str).str.startswith("failed").sum()

print("\n提取完成。")
print(f"文本型PDF总数: {len(text_df)}")
print(f"提取成功: {success_count}")
print(f"提取失败: {failed_count}")
print(f"提取结果目录: {OUTPUT_DIR}")