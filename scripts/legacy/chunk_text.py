from pathlib import Path
import json
import re
from tqdm import tqdm

# ========= 1. 路径配置 =========
INPUT_DIR = Path(r"E:\WORK\data\cleaned_text")
OUTPUT_DIR = Path(r"E:\WORK\data\chunks")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ========= 2. 参数配置 =========
MIN_CHUNK_LEN = 80       # 太短的段落会尝试和后面合并
MAX_CHUNK_LEN = 500      # 太长的段落按长度切分
ONLY_HIGH_QUALITY = True # 只处理 high_quality 文本

# ========= 3. 工具函数 =========
def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def split_page_into_paragraphs(text: str):
    """
    先按空行拆段；
    如果没有明显空行，就按单行继续保留。
    """
    text = normalize_text(text)
    if not text:
        return []

    if "\n\n" in text:
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    else:
        parts = [p.strip() for p in text.split("\n") if p.strip()]

    return parts

def split_long_text(text: str, max_len=500):
    """
    对超长段落进行二次切分：
    优先按句号、分号、换行等断开；
    实在不行再按长度硬切。
    """
    text = normalize_text(text)
    if len(text) <= max_len:
        return [text]

    # 先按句子边界粗分
    sentences = re.split(r'(?<=[。！？；;])', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current = ""

    for sent in sentences:
        if len(current) + len(sent) <= max_len:
            current += sent
        else:
            if current:
                chunks.append(current.strip())

            # 如果单句本身就超长，则硬切
            if len(sent) > max_len:
                for i in range(0, len(sent), max_len):
                    piece = sent[i:i + max_len].strip()
                    if piece:
                        chunks.append(piece)
                current = ""
            else:
                current = sent

    if current.strip():
        chunks.append(current.strip())

    return chunks

def merge_short_paragraphs(paragraphs, min_len=80):
    """
    将过短段落与后一个段落合并，减少碎片。
    """
    if not paragraphs:
        return []

    merged = []
    buffer = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if not buffer:
            buffer = para
        else:
            if len(buffer) < min_len:
                buffer = buffer + "\n" + para
            else:
                merged.append(buffer.strip())
                buffer = para

    if buffer.strip():
        merged.append(buffer.strip())

    return merged

# ========= 4. 批量处理 =========
json_files = list(INPUT_DIR.rglob("*.json"))

doc_success = 0
doc_failed = 0
total_chunks = 0

for json_path in tqdm(json_files, desc="文本切块"):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        quality_info = data.get("text_quality", {})
        quality_label = quality_info.get("quality_label", "")

        if ONLY_HIGH_QUALITY and quality_label != "high_quality":
            continue

        chunks = []
        chunk_counter = 1

        file_stem = data.get("file_stem", "")
        file_name = data.get("file_name", "")
        relative_path = data.get("relative_path", "")
        level_1_dir = data.get("level_1_dir", "")
        level_2_dir = data.get("level_2_dir", "")
        level_3_dir = data.get("level_3_dir", "")

        for page in data.get("cleaned_pages", []):
            page_num = page.get("page_num")
            is_toc_page = page.get("is_toc_page", False)
            text = page.get("text", "")

            # 跳过目录页
            if is_toc_page:
                continue

            text = normalize_text(text)
            if not text:
                continue

            paragraphs = split_page_into_paragraphs(text)
            paragraphs = merge_short_paragraphs(paragraphs, min_len=MIN_CHUNK_LEN)

            final_parts = []
            for para in paragraphs:
                para_parts = split_long_text(para, max_len=MAX_CHUNK_LEN)
                final_parts.extend([p for p in para_parts if p.strip()])

            for part in final_parts:
                chunk_record = {
                    "doc_id": file_stem,
                    "file_name": file_name,
                    "relative_path": relative_path,
                    "level_1_dir": level_1_dir,
                    "level_2_dir": level_2_dir,
                    "level_3_dir": level_3_dir,
                    "page_num": page_num,
                    "chunk_id": f"{file_stem}_chunk_{chunk_counter:04d}",
                    "text": part.strip(),
                    "text_len": len(part.strip()),
                    "text_quality_label": quality_label
                }
                chunks.append(chunk_record)
                chunk_counter += 1

        # 输出路径保持和原目录一致
        rel_path = json_path.relative_to(INPUT_DIR)
        out_path = OUTPUT_DIR / rel_path
        out_path = out_path.with_suffix(".jsonl")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w", encoding="utf-8") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

        total_chunks += len(chunks)
        doc_success += 1

    except Exception as e:
        doc_failed += 1
        print(f"处理失败: {json_path} -> {e}")

print("\n切块完成。")
print(f"成功处理文档数: {doc_success}")
print(f"失败文档数: {doc_failed}")
print(f"生成 chunks 总数: {total_chunks}")
print(f"输出目录: {OUTPUT_DIR}")