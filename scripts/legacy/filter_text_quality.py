from pathlib import Path
import json
import re
import csv
from tqdm import tqdm

# ========= 1. 路径配置 =========
INPUT_DIR = Path(r"E:\WORK\data\cleaned_text")
META_DIR = Path(r"E:\WORK\data\meta")
REPORT_CSV = META_DIR / "text_quality_report.csv"

META_DIR.mkdir(parents=True, exist_ok=True)

# ========= 2. 工具函数 =========
def count_chinese_chars(text: str) -> int:
    return len(re.findall(r'[\u4e00-\u9fff]', text))

def count_english_chars(text: str) -> int:
    return len(re.findall(r'[A-Za-z]', text))

def count_digits(text: str) -> int:
    return len(re.findall(r'\d', text))

def count_visible_chars(text: str) -> int:
    # 可见非空白字符数
    return len(re.findall(r'\S', text))

def count_abnormal_chars(text: str) -> int:
    """
    统计常见异常字符/乱码痕迹：
    - 大量反斜杠
    - 竖线
    - 波浪线
    - 特殊零散符号
    - 重复乱码样式
    """
    patterns = [
        r'\\',
        r'\|',
        r'~',
        r'`',
        r'�',
        r'□',
        r'○',
        r'¤',
        r'§',
        r'¦',
        r'¬',
        r'¢',
        r'£',
        r'¥',
    ]
    total = 0
    for p in patterns:
        total += len(re.findall(p, text))
    return total

def count_punctuation_noise(text: str) -> int:
    # 统计高频噪声符号，避免正常中文标点过度影响
    patterns = [
        r'[\.．·•…。]{4,}',   # 长点线
        r'[_—\-]{4,}',       # 长横线
        r'[/\\]{3,}',        # 连续斜杠
        r'[|]{3,}',          # 连续竖线
    ]
    total = 0
    for p in patterns:
        matches = re.findall(p, text)
        total += sum(len(m) for m in matches)
    return total

def count_garbled_segments(text: str) -> int:
    """
    统计疑似乱码片段：
    - 很短但符号特别多的片段
    - 连续英文字母/符号混杂且缺乏中文语义
    """
    segments = re.split(r'[\n。；;]', text)
    bad = 0

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        chinese = count_chinese_chars(seg)
        visible = count_visible_chars(seg)
        abnormal = count_abnormal_chars(seg)
        english = count_english_chars(seg)

        # 片段很“花”，但中文很少
        if visible >= 15 and chinese <= 2 and abnormal >= 3:
            bad += 1
            continue

        # 很长，但看起来不像正常中文句子
        if visible >= 25 and chinese / max(visible, 1) < 0.08 and (abnormal + english) / max(visible, 1) > 0.6:
            bad += 1

    return bad

def evaluate_text_quality(text: str):
    visible_chars = count_visible_chars(text)
    chinese_chars = count_chinese_chars(text)
    english_chars = count_english_chars(text)
    digits = count_digits(text)
    abnormal_chars = count_abnormal_chars(text)
    punctuation_noise = count_punctuation_noise(text)
    garbled_segments = count_garbled_segments(text)

    chinese_ratio = chinese_chars / visible_chars if visible_chars else 0
    abnormal_ratio = abnormal_chars / visible_chars if visible_chars else 0
    noise_ratio = (abnormal_chars + punctuation_noise) / visible_chars if visible_chars else 0

    # ========= 质量判断规则 =========
    # 规则是工程经验规则，适合先筛选可用文本
    if visible_chars < 80:
        quality_label = "low_quality"
        quality_reason = "text_too_short"
    elif chinese_ratio >= 0.25 and abnormal_ratio < 0.03 and garbled_segments <= 2:
        quality_label = "high_quality"
        quality_reason = "readable_chinese_text"
    elif chinese_ratio >= 0.12 and noise_ratio < 0.20 and garbled_segments <= 8:
        quality_label = "mixed_quality"
        quality_reason = "partially_readable"
    else:
        quality_label = "low_quality"
        quality_reason = "garbled_or_noisy"

    metrics = {
        "visible_chars": visible_chars,
        "chinese_chars": chinese_chars,
        "english_chars": english_chars,
        "digits": digits,
        "abnormal_chars": abnormal_chars,
        "punctuation_noise": punctuation_noise,
        "garbled_segments": garbled_segments,
        "chinese_ratio": round(chinese_ratio, 4),
        "abnormal_ratio": round(abnormal_ratio, 4),
        "noise_ratio": round(noise_ratio, 4),
        "quality_label": quality_label,
        "quality_reason": quality_reason,
    }
    return metrics

# ========= 3. 批量处理 =========
json_files = list(INPUT_DIR.rglob("*.json"))

report_rows = []
success_count = 0
failed_count = 0

for json_path in tqdm(json_files, desc="筛选文本质量"):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        text = data.get("cleaned_full_text", "")
        metrics = evaluate_text_quality(text)

        # 回写到 JSON 中
        data["text_quality"] = {
            "quality_label": metrics["quality_label"],
            "quality_reason": metrics["quality_reason"],
            "visible_chars": metrics["visible_chars"],
            "chinese_chars": metrics["chinese_chars"],
            "english_chars": metrics["english_chars"],
            "digits": metrics["digits"],
            "abnormal_chars": metrics["abnormal_chars"],
            "punctuation_noise": metrics["punctuation_noise"],
            "garbled_segments": metrics["garbled_segments"],
            "chinese_ratio": metrics["chinese_ratio"],
            "abnormal_ratio": metrics["abnormal_ratio"],
            "noise_ratio": metrics["noise_ratio"],
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        report_rows.append([
            data.get("file_stem", ""),
            data.get("file_name", ""),
            data.get("relative_path", ""),
            data.get("level_1_dir", ""),
            data.get("level_2_dir", ""),
            data.get("level_3_dir", ""),
            metrics["quality_label"],
            metrics["quality_reason"],
            metrics["visible_chars"],
            metrics["chinese_chars"],
            metrics["english_chars"],
            metrics["digits"],
            metrics["abnormal_chars"],
            metrics["punctuation_noise"],
            metrics["garbled_segments"],
            metrics["chinese_ratio"],
            metrics["abnormal_ratio"],
            metrics["noise_ratio"],
            str(json_path),
        ])

        success_count += 1

    except Exception as e:
        failed_count += 1
        report_rows.append([
            "", "", str(json_path), "", "", "",
            "failed", str(e)[:100],
            "", "", "", "", "", "", "", "", "", "", str(json_path)
        ])

# ========= 4. 写出报告 =========
with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow([
        "file_stem",
        "file_name",
        "relative_path",
        "level_1_dir",
        "level_2_dir",
        "level_3_dir",
        "quality_label",
        "quality_reason",
        "visible_chars",
        "chinese_chars",
        "english_chars",
        "digits",
        "abnormal_chars",
        "punctuation_noise",
        "garbled_segments",
        "chinese_ratio",
        "abnormal_ratio",
        "noise_ratio",
        "json_path"
    ])
    writer.writerows(report_rows)

# ========= 5. 统计输出 =========
high_count = sum(1 for r in report_rows if len(r) > 6 and r[6] == "high_quality")
mixed_count = sum(1 for r in report_rows if len(r) > 6 and r[6] == "mixed_quality")
low_count = sum(1 for r in report_rows if len(r) > 6 and r[6] == "low_quality")

print("\n文本质量筛选完成。")
print(f"成功处理: {success_count}")
print(f"失败: {failed_count}")
print(f"high_quality: {high_count}")
print(f"mixed_quality: {mixed_count}")
print(f"low_quality: {low_count}")
print(f"质量报告已保存到: {REPORT_CSV}")