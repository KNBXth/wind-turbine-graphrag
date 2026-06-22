from pathlib import Path
import pandas as pd
from tqdm import tqdm
import fitz  # PyMuPDF
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import config

# ========= 1. 路径配置 =========
INVENTORY_CSV = config.PDF_INVENTORY_CSV
OUTPUT_CSV = config.PDF_INVENTORY_CSV  # 直接覆盖更新

# ========= 2. 读取清单 =========
df = pd.read_csv(INVENTORY_CSV)

# 如果重复运行，避免列不存在报错
if "page_count" not in df.columns:
    df["page_count"] = None
if "sample_text_len" not in df.columns:
    df["sample_text_len"] = None
if "is_scanned_suspect" not in df.columns:
    df["is_scanned_suspect"] = None
if "detect_status" not in df.columns:
    df["detect_status"] = None

# ========= 3. 检测函数 =========
def detect_pdf_text_info(pdf_path_str):
    try:
        pdf_path = Path(pdf_path_str)
        doc = fitz.open(pdf_path)

        page_count = len(doc)
        sample_pages = min(5, page_count)

        all_text = []
        for i in range(sample_pages):
            page = doc[i]
            text = page.get_text("text")
            if text:
                all_text.append(text)

        sample_text = "\n".join(all_text).strip()
        sample_text_len = len(sample_text)

        # 经验阈值：前5页文字太少，怀疑是扫描件
        is_scanned_suspect = sample_text_len < 200

        return page_count, sample_text_len, is_scanned_suspect, "success"

    except Exception as e:
        return -1, 0, True, f"failed: {str(e)[:100]}"

# ========= 4. 批量检测 =========
for idx, row in tqdm(df.iterrows(), total=len(df), desc="检测PDF类型"):
    # 如果已经成功检测过，可以跳过；想强制重跑就把这段if去掉
    if pd.notna(row["detect_status"]) and str(row["detect_status"]).startswith("success"):
        continue

    page_count, sample_text_len, is_scanned_suspect, detect_status = detect_pdf_text_info(row["full_path"])

    df.at[idx, "page_count"] = page_count
    df.at[idx, "sample_text_len"] = sample_text_len
    df.at[idx, "is_scanned_suspect"] = is_scanned_suspect
    df.at[idx, "detect_status"] = detect_status

# ========= 5. 保存结果 =========
df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

# ========= 6. 统计输出 =========
total_count = len(df)
success_count = (df["detect_status"].astype(str).str.startswith("success")).sum()
scanned_count = (df["is_scanned_suspect"] == True).sum()
text_count = (df["is_scanned_suspect"] == False).sum()
failed_count = total_count - success_count

print(f"\n检测完成。")
print(f"总文件数: {total_count}")
print(f"成功检测: {success_count}")
print(f"疑似扫描件: {scanned_count}")
print(f"疑似文本型PDF: {text_count}")
print(f"检测失败: {failed_count}")
print(f"结果已更新到: {OUTPUT_CSV}")