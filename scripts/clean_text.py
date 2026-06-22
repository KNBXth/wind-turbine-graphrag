from pathlib import Path
import json
import re
from tqdm import tqdm
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import config

# ========= 1. 路径配置 =========
INPUT_DIR = config.EXTRACTED_TEXT_DIR
OUTPUT_DIR = config.CLEANED_TEXT_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ========= 2. 文本清洗函数 =========
def clean_page_text(text: str) -> str:
    if not text:
        return ""

    # 统一换行
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 全角空格转半角
    text = text.replace("\u3000", " ")

    # 去掉目录中的长点线、符号线
    text = re.sub(r"[\.．·•…。]{4,}", " ", text)
    text = re.sub(r"[_—\-]{4,}", " ", text)

    # 去掉单独页码行，如：1 / - 1 - / 第1页
    text = re.sub(r"^\s*[-—]?\s*\d+\s*[-—]?\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*第\s*\d+\s*页\s*$", "", text, flags=re.MULTILINE)

    # 去掉过多空格和制表符
    text = re.sub(r"[ \t]+", " ", text)

    # 清理每行首尾空白
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    # 压缩连续空行
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()

# ========= 3. 判断是否像目录页 =========
def is_toc_page(text: str) -> bool:
    if not text:
        return False

    text = text.strip()

    # 规则1：前部直接出现“目录”
    if "目录" in text[:100]:
        return True

    # 规则2：大量点线/符号线
    dotline_count = len(re.findall(r"[\.．·•…。]{4,}", text))
    dashline_count = len(re.findall(r"[_—\-]{4,}", text))

    # 规则3：很多“短标题 + 页码”形式
    short_line_count = 0
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    for line in lines:
        if len(line) <= 80 and re.search(r"\d+\s*$", line):
            short_line_count += 1

    if dotline_count + dashline_count >= 3 and short_line_count >= 3:
        return True

    # 规则4：前几行出现较多章节式标题
    chapter_like = 0
    for line in lines[:15]:
        if re.match(r"^(\d+(\.\d+)*|第[一二三四五六七八九十百]+[章节部分篇])", line):
            chapter_like += 1

    if chapter_like >= 5 and short_line_count >= 3:
        return True

    return False

# ========= 4. 批量处理 =========
json_files = list(INPUT_DIR.rglob("*.json"))

success_count = 0
failed_count = 0

for json_path in tqdm(json_files, desc="清洗文本"):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cleaned_pages = []
        full_text_parts = []

        for page in data.get("pages", []):
            page_num = page.get("page_num")
            raw_text = page.get("text", "")

            # 空页直接跳过
            if not raw_text or not raw_text.strip():
                continue

            # 先清洗，再判断是否目录页
            cleaned_text = clean_page_text(raw_text)

            if not cleaned_text:
                continue

            toc_flag = is_toc_page(cleaned_text)

            cleaned_pages.append({
                "page_num": page_num,
                "is_toc_page": toc_flag,
                "text": cleaned_text
            })

            # 目录页不拼入正文全文
            if not toc_flag:
                full_text_parts.append(cleaned_text)

        cleaned_full_text = "\n\n".join(full_text_parts).strip()

        out_data = {
            "file_stem": data.get("file_stem", ""),
            "file_name": data.get("file_name", ""),
            "full_path": data.get("full_path", ""),
            "relative_path": data.get("relative_path", ""),
            "level_1_dir": data.get("level_1_dir", ""),
            "level_2_dir": data.get("level_2_dir", ""),
            "level_3_dir": data.get("level_3_dir", ""),
            "page_count": data.get("page_count", 0),
            "cleaned_pages": cleaned_pages,
            "cleaned_full_text": cleaned_full_text
        }

        rel_path = json_path.relative_to(INPUT_DIR)
        out_path = OUTPUT_DIR / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out_data, f, ensure_ascii=False, indent=2)

        success_count += 1

    except Exception as e:
        failed_count += 1
        print(f"处理失败: {json_path} -> {e}")

print("\n清洗完成。")
print(f"成功: {success_count}")
print(f"失败: {failed_count}")
print(f"输出目录: {OUTPUT_DIR}")