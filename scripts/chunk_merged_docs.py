from pathlib import Path
import json
import re
from typing import Any, Dict, List, Optional
from tqdm import tqdm
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import config

# ========= 1. 路径配置 =========
INPUT_DIR = config.MERGED_DOCS_DIR
OUTPUT_DIR = config.CHUNKS_DIR
DOC_CHUNK_DIR = OUTPUT_DIR / "docs"
DOC_CHUNK_DIR.mkdir(parents=True, exist_ok=True)

INDEX_OUTPUT_PATH = OUTPUT_DIR / "chunk_index.jsonl"

# ========= 2. 参数配置 =========
# 调试用：限制处理文档数，正式跑时设为 None
LIMIT_DOCS: Optional[int] = None

# 是否跳过目录页
SKIP_TOC_PAGE = True

# 是否跳过空页
SKIP_EMPTY_PAGE = True

# 最小 chunk 长度：太短则尝试与后续合并
MIN_CHUNK_LEN = 120

# 最大 chunk 长度：太长则拆分
MAX_CHUNK_LEN = 500

# 如果单页太短，是否允许和下一页拼接
ALLOW_CROSS_PAGE_MERGE = True


# ========= 3. 基础工具函数 =========
def load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_jsonl(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_page_into_paragraphs(text: str) -> List[str]:
    """
    优先按空行拆段；
    没有空行时按单行拆。
    """
    text = normalize_text(text)
    if not text:
        return []

    if "\n\n" in text:
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    else:
        parts = [p.strip() for p in text.split("\n") if p.strip()]

    return parts


def split_long_text(text: str, max_len: int = 500) -> List[str]:
    """
    对超长段落做二次切分：
    优先按句号、分号、问号、感叹号等切分；
    再不行按长度硬切。
    """
    text = normalize_text(text)
    if not text:
        return []

    if len(text) <= max_len:
        return [text]

    # 先按句子边界切
    sentences = re.split(r'(?<=[。！？；;.!?])', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current = ""

    for sent in sentences:
        if len(current) + len(sent) <= max_len:
            current += sent
        else:
            if current.strip():
                chunks.append(current.strip())

            # 单句仍超长，硬切
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


def merge_short_units(units: List[Dict[str, Any]], min_len: int = 120, allow_cross_page: bool = True) -> List[Dict[str, Any]]:
    """
    把过短段落向后合并。
    units 元素结构：
    {
      "text": "...",
      "page_start": 1,
      "page_end": 1
    }
    """
    if not units:
        return []

    merged = []
    buffer = None

    for unit in units:
        text = unit["text"].strip()
        if not text:
            continue

        if buffer is None:
            buffer = dict(unit)
            continue

        same_page = buffer["page_end"] == unit["page_start"]

        can_merge = (
            len(buffer["text"]) < min_len and
            (allow_cross_page or same_page)
        )

        if can_merge:
            buffer["text"] = buffer["text"].rstrip() + "\n" + text
            buffer["page_end"] = unit["page_end"]
        else:
            merged.append(buffer)
            buffer = dict(unit)

    if buffer is not None:
        merged.append(buffer)

    return merged


def build_chunk_id(doc_id: str, idx: int) -> str:
    return f"{doc_id}_chunk_{idx:04d}"


# ========= 4. 单文档处理 =========
def build_units_from_doc(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    从 merged doc 的 pages 构造最原始的段落单元
    """
    units: List[Dict[str, Any]] = []

    for page in doc.get("pages", []):
        page_num = page.get("page_num", 0)
        is_toc_page = bool(page.get("is_toc_page", False))
        text = normalize_text(page.get("text", ""))

        if SKIP_TOC_PAGE and is_toc_page:
            continue

        if SKIP_EMPTY_PAGE and not text:
            continue

        if not text:
            continue

        paragraphs = split_page_into_paragraphs(text)

        for para in paragraphs:
            para = normalize_text(para)
            if not para:
                continue

            # 先对超长段落切分
            pieces = split_long_text(para, max_len=MAX_CHUNK_LEN)

            for piece in pieces:
                piece = normalize_text(piece)
                if not piece:
                    continue

                units.append({
                    "text": piece,
                    "page_start": page_num,
                    "page_end": page_num,
                })

    return units


def chunk_one_doc(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    对单个 merged doc 进行 chunk
    """
    doc_id = doc.get("doc_id", "")
    title = doc.get("title", "")
    file_name = doc.get("file_name", "")
    relative_path = doc.get("relative_path", "")
    doc_type = doc.get("doc_type", "standard")

    units = build_units_from_doc(doc)

    # 合并过短段落
    units = merge_short_units(
        units,
        min_len=MIN_CHUNK_LEN,
        allow_cross_page=ALLOW_CROSS_PAGE_MERGE,
    )

    chunks: List[Dict[str, Any]] = []
    for idx, unit in enumerate(units, start=1):
        text = normalize_text(unit["text"])
        if not text:
            continue

        chunks.append({
            "chunk_id": build_chunk_id(doc_id, idx),
            "doc_id": doc_id,
            "title": title,
            "file_name": file_name,
            "relative_path": relative_path,
            "doc_type": doc_type,
            "page_start": unit["page_start"],
            "page_end": unit["page_end"],
            "chunk_text": text,
            "chunk_len": len(text),
        })

    return chunks


# ========= 5. 主流程 =========
def main():
    input_files = sorted(INPUT_DIR.glob("*.json"))

    if LIMIT_DOCS is not None:
        input_files = input_files[:LIMIT_DOCS]
        print(f"[INFO] 仅处理前 {len(input_files)} 个 merged docs")

    print(f"待切块文档数: {len(input_files)}")

    if not input_files:
        print("未找到 merged docs。")
        return

    total_chunks = 0
    success_docs = 0
    failed_docs = 0
    chunk_index_rows: List[Dict[str, Any]] = []

    for doc_path in tqdm(input_files, desc="切块 merged docs"):
        try:
            doc = load_json(doc_path)
            chunks = chunk_one_doc(doc)

            # 每个文档输出一个 jsonl
            out_path = DOC_CHUNK_DIR / f"{doc.get('doc_id', doc_path.stem)}.jsonl"
            save_jsonl(chunks, out_path)

            total_chunks += len(chunks)
            success_docs += 1

            chunk_index_rows.append({
                "doc_id": doc.get("doc_id", ""),
                "title": doc.get("title", ""),
                "file_name": doc.get("file_name", ""),
                "relative_path": doc.get("relative_path", ""),
                "doc_type": doc.get("doc_type", "standard"),
                "page_count": doc.get("page_count", 0),
                "chunk_count": len(chunks),
                "chunk_file_path": str(out_path),
            })

        except Exception as e:
            failed_docs += 1
            print(f"[ERROR] 处理失败: {doc_path} -> {e}")

    save_jsonl(chunk_index_rows, INDEX_OUTPUT_PATH)

    print("\n切块完成。")
    print(f"成功处理文档数: {success_docs}")
    print(f"失败文档数: {failed_docs}")
    print(f"生成 chunks 总数: {total_chunks}")
    print(f"chunk 文档输出目录: {DOC_CHUNK_DIR}")
    print(f"chunk 索引文件: {INDEX_OUTPUT_PATH}")


if __name__ == "__main__":
    main()