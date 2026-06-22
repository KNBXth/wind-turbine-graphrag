from pathlib import Path
import json
import re
from typing import Any
from tqdm import tqdm
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import config

# ========= 1. 路径配置 =========
INPUT_DIR = config.OCR_EXTRACTED_DIR
OUTPUT_DIR = config.OCR_CLEANED_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ========= 2. 清洗参数 =========
# 这里故意设置得更宽松，避免误杀有价值页面
MIN_TEXT_LEN = 15
MIN_LINE_COUNT = 1
MIN_VISIBLE_TEXT_RATIO = 0.15

# 是否保留被判定为低质量页面的记录
# True = 保留，只打标记 is_filtered=True
# False = 真正丢弃（不建议）
KEEP_FILTERED_RECORDS = True

# 是否限制处理文件数（调试用）
LIMIT_FILES = None  # 例如 10

# ========= 3. 常见噪声模式 =========
NOISE_PATTERNS = [
    r"学\s*兔\s*兔",
    r"www\s*\.\s*bzfxw\s*\.\s*com",
    r"bzfxw\s*\.\s*com",
    r"w\s*w\s*w\s*\.\s*b\s*z\s*f\s*x\s*w\s*\.\s*c\s*o\s*m",
    r"标\s*准\s*下\s*载",
    r"免\s*费\s*下\s*载",
    r"仅\s*供.*?使\s*用",
    r"内\s*部\s*资\s*料",
    r"扫\s*描\s*全\s*能\s*王",
    r"仅\s*供\s*学\s*习\s*交\s*流",
    r"更\s*多\s*免\s*费\s*资\s*料\s*下\s*载",
]

# 疑似纯噪声行
PURE_NOISE_LINE_PATTERNS = [
    r"^\s*$",
    r"^[\-_=~·•.。,:：;；、\s]+$",
    r"^\d+\s*$",
    r"^第\s*\d+\s*页\s*$",
    r"^Page\s*\d+\s*$",
    r"^www\..*$",
    r"^bzfxw.*$",
]

# 标题 / 条款 / 图表 / 附录特征
TITLE_PATTERNS = [
    r"^\d+(\.\d+)*\s*[^\d].*$",           # 1 / 1.1 / 1.1.1 ...
    r"^附录\s*[A-ZＡ-Ｚ一二三四五六七八九十].*$",
    r"^表\s*[A-Za-z0-9一二三四五六七八九十\.\-].*$",
    r"^图\s*[A-Za-z0-9一二三四五六七八九十\.\-].*$",
    r"^前言\s*$",
    r"^目次\s*$",
    r"^目录\s*$",
    r"^范围\s*$",
    r"^规范性引用文件\s*$",
    r"^术语和定义\s*$",
    r"^技术要求\s*$",
    r"^试验方法\s*$",
    r"^检验规则\s*$",
    r"^运行与维护\s*$",
    r"^总则\s*$",
    r"^引用标准\s*$",
]

# 可能是目录行
TOC_LINE_PATTERNS = [
    r"^.*\.{2,}\s*\d+\s*$",
    r"^.*…{2,}\s*\d+\s*$",
]

# 常见低价值页特征（不直接删，只辅助判断）
LOW_VALUE_HINT_PATTERNS = [
    r"责任编辑",
    r"印刷",
    r"定价",
    r"统一书号",
    r"版权所有",
    r"侵权必究",
]


# ========= 4. 基础 IO =========
def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def save_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ========= 5. 判定函数 =========
def is_title_like(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return any(re.match(pattern, s) for pattern in TITLE_PATTERNS)


def is_toc_like(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return any(re.match(pattern, s) for pattern in TOC_LINE_PATTERNS)


def is_pure_noise_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    return any(re.match(pattern, s, flags=re.IGNORECASE) for pattern in PURE_NOISE_LINE_PATTERNS)


def contains_low_value_hint(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in LOW_VALUE_HINT_PATTERNS)


# ========= 6. 文本清洗 =========
def remove_noise_patterns(text: str) -> str:
    cleaned = text
    for pattern in NOISE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def normalize_spaces(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fix_common_ocr_noise(text: str) -> str:
    text = remove_noise_patterns(text)

    # 中文之间多余空格去掉
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)

    # 中文与标点之间多余空格
    text = re.sub(r"\s+([，。；：！？、）】》])", r"\1", text)
    text = re.sub(r"([（【《])\s+", r"\1", text)

    # 连续破折号统一
    text = re.sub(r"[—–]{2,}", "——", text)

    # 奇怪分隔符
    text = re.sub(r"[|¦]+", " ", text)

    # 多空格压缩
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


def should_keep_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if is_pure_noise_line(s):
        return False
    return True


def merge_lines(lines: list[str]) -> list[str]:
    """
    更稳妥的行合并策略：
    - 标题 / 条款号 / 目录行单独保留
    - 普通正文尽量保留换行，不做激进拼接
    - 连续短碎片才适度合并
    """
    merged: list[str] = []
    buffer = ""

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        line = fix_common_ocr_noise(line)
        if not line:
            continue

        if not should_keep_line(line):
            continue

        if is_title_like(line) or is_toc_like(line):
            if buffer.strip():
                merged.append(buffer.strip())
                buffer = ""
            merged.append(line)
            continue

        # 如果当前 buffer 为空，先放进去
        if not buffer:
            buffer = line
            continue

        # 两行都很短，可能是被错误切开的短句，适度拼接
        if len(buffer) < 15 and len(line) < 15:
            buffer += line
        else:
            merged.append(buffer.strip())
            buffer = line

    if buffer.strip():
        merged.append(buffer.strip())

    return merged


def clean_page_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = fix_common_ocr_noise(text)

    raw_lines = [x.strip() for x in text.split("\n")]
    raw_lines = [x for x in raw_lines if x]

    merged_lines = merge_lines(raw_lines)

    cleaned = "\n".join(merged_lines)
    cleaned = normalize_spaces(cleaned)

    return cleaned.strip()


# ========= 7. 页面质量评估 =========
def calc_visible_text_ratio(text: str) -> float:
    visible = re.sub(r"\s+", "", text)
    if not visible:
        return 0.0

    useful = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", visible)
    return len(useful) / max(len(visible), 1)


def page_has_title_or_structure(cleaned_text: str) -> bool:
    lines = [x.strip() for x in cleaned_text.split("\n") if x.strip()]
    title_count = sum(1 for x in lines if is_title_like(x))
    toc_count = sum(1 for x in lines if is_toc_like(x))
    return title_count >= 1 or toc_count >= 2


def should_drop_page(cleaned_text: str, ocr_line_count: Any = None) -> tuple[bool, str]:
    """
    这里只做“建议过滤”判断，不建议直接真删页。
    """
    if not cleaned_text:
        return True, "empty_after_clean"

    # 标题页 / 目录页 / 条款页豁免
    if page_has_title_or_structure(cleaned_text):
        return False, ""

    if len(cleaned_text) < MIN_TEXT_LEN:
        return True, f"text_too_short<{MIN_TEXT_LEN}"

    line_count = len([x for x in cleaned_text.split("\n") if x.strip()])
    if line_count < MIN_LINE_COUNT:
        return True, f"line_count_too_small<{MIN_LINE_COUNT}"

    visible_ratio = calc_visible_text_ratio(cleaned_text)
    if visible_ratio < MIN_VISIBLE_TEXT_RATIO:
        return True, f"visible_text_ratio_too_low<{MIN_VISIBLE_TEXT_RATIO}"

    # OCR 行数作为弱辅助信号
    try:
        if ocr_line_count is not None and int(ocr_line_count) <= 0:
            return True, "ocr_line_count<=0"
    except Exception:
        pass

    # 命中低价值特征且文本又很短，标记为低价值
    if len(cleaned_text) < 80 and contains_low_value_hint(cleaned_text):
        return True, "low_value_page_hint"

    return False, ""


# ========= 8. 单页记录处理 =========
def clean_one_record(row: dict[str, Any]) -> dict[str, Any]:
    text = row.get("text", "") or ""
    cleaned_text = clean_page_text(text)

    drop, reason = should_drop_page(cleaned_text, row.get("ocr_line_count"))

    out = dict(row)
    out["raw_text_len"] = len(text)
    out["clean_text_len"] = len(cleaned_text)
    out["clean_text"] = cleaned_text
    out["is_filtered"] = drop
    out["filter_reason"] = reason if drop else ""
    out["visible_text_ratio"] = round(calc_visible_text_ratio(cleaned_text), 4) if cleaned_text else 0.0
    out["has_structure_hint"] = page_has_title_or_structure(cleaned_text)

    return out


# ========= 9. 单文件处理（支持断点续跑） =========
def process_one_file(input_path: Path, output_path: Path) -> dict[str, Any]:
    input_rows = load_jsonl(input_path)
    input_count = len(input_rows)

    if output_path.exists():
        try:
            output_rows = load_jsonl(output_path)
            output_count = len(output_rows)

            if output_count == input_count:
                return {
                    "status": "skip_exists",
                    "file": input_path.name,
                    "total_pages": input_count,
                    "kept_pages": None,
                    "filtered_pages": None,
                    "written_pages": None,
                }
            else:
                print(
                    f"[WARN] 检测到不完整清洗结果，重新处理: {input_path.name} "
                    f"(输入 {input_count} 行, 输出 {output_count} 行)"
                )
                try:
                    output_path.unlink()
                except Exception:
                    pass

        except Exception as e:
            print(f"[WARN] 读取已有清洗结果失败，准备重跑: {input_path.name}, error={e}")
            try:
                output_path.unlink()
            except Exception:
                pass

    cleaned_rows: list[dict[str, Any]] = []
    kept_count = 0
    filtered_count = 0
    written_count = 0

    for row in input_rows:
        cleaned = clean_one_record(row)

        if cleaned["is_filtered"]:
            filtered_count += 1
        else:
            kept_count += 1

        if KEEP_FILTERED_RECORDS:
            cleaned_rows.append(cleaned)
            written_count += 1
        else:
            if not cleaned["is_filtered"]:
                cleaned_rows.append(cleaned)
                written_count += 1

    save_jsonl(cleaned_rows, output_path)

    return {
        "status": "ok",
        "file": input_path.name,
        "total_pages": input_count,
        "kept_pages": kept_count,
        "filtered_pages": filtered_count,
        "written_pages": written_count,
    }


# ========= 10. 主流程 =========
def main() -> None:
    input_files = list(INPUT_DIR.glob("*.jsonl"))

    if LIMIT_FILES is not None:
        input_files = input_files[:LIMIT_FILES]
        print(f"[INFO] 仅处理前 {len(input_files)} 个文件")

    print(f"待清洗 OCR 文件数量: {len(input_files)}")

    if not input_files:
        print("未找到 OCR jsonl 文件。")
        return

    total_files = 0
    total_pages = 0
    total_kept = 0
    total_filtered = 0
    total_written = 0

    summary: dict[str, int] = {
        "ok": 0,
        "skip_exists": 0,
    }

    for input_path in tqdm(input_files, desc="清洗 OCR 文本"):
        output_path = OUTPUT_DIR / input_path.name
        stat = process_one_file(input_path, output_path)

        summary[stat["status"]] = summary.get(stat["status"], 0) + 1
        total_files += 1
        total_pages += stat["total_pages"]

        if stat["status"] == "ok":
            total_kept += int(stat["kept_pages"] or 0)
            total_filtered += int(stat["filtered_pages"] or 0)
            total_written += int(stat["written_pages"] or 0)

    print("\nOCR 清洗完成。")
    print(f"文件数: {total_files}")
    print(f"总页数: {total_pages}")
    print(f"本次新清洗文件: {summary.get('ok', 0)}")
    print(f"跳过已完成文件: {summary.get('skip_exists', 0)}")
    print(f"本次保留页数: {total_kept}")
    print(f"本次标记过滤页数: {total_filtered}")
    print(f"本次实际写出页数: {total_written}")
    print(f"输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()