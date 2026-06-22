from pathlib import Path
import csv
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import config

# ========= 1. 路径配置 =========
RAW_DIR = config.RAW_PDF_DIR
META_DIR = config.META_DIR
OUTPUT_CSV = META_DIR / "pdf_inventory.csv"

# ========= 2. 创建输出目录 =========
META_DIR.mkdir(parents=True, exist_ok=True)

# ========= 3. 扫描 PDF =========
pdf_rows = []

for pdf_path in RAW_DIR.rglob("*"):
    if pdf_path.is_file() and pdf_path.suffix.lower() == ".pdf":
        rel_path = pdf_path.relative_to(RAW_DIR)

        parts = rel_path.parts
        level_1 = parts[0] if len(parts) > 0 else ""
        level_2 = parts[1] if len(parts) > 1 else ""
        level_3 = parts[2] if len(parts) > 2 else ""

        size_mb = round(pdf_path.stat().st_size / (1024 * 1024), 2)

        pdf_rows.append([
            pdf_path.stem,                 # 文件名（不含扩展名）
            pdf_path.name,                 # 文件名（含扩展名）
            str(pdf_path),                 # 完整路径
            str(rel_path),                 # 相对路径
            level_1,                       # 一级目录
            level_2,                       # 二级目录
            level_3,                       # 三级目录
            pdf_path.suffix.lower(),       # 扩展名
            size_mb                        # 文件大小(MB)
        ])

# ========= 4. 排序 =========
pdf_rows.sort(key=lambda x: x[3])

# ========= 5. 写出 CSV =========
with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow([
        "file_stem",
        "file_name",
        "full_path",
        "relative_path",
        "level_1_dir",
        "level_2_dir",
        "level_3_dir",
        "suffix",
        "size_mb"
    ])
    writer.writerows(pdf_rows)

print(f"扫描完成，共发现 {len(pdf_rows)} 个 PDF 文件。")
print(f"清单已保存到：{OUTPUT_CSV}")