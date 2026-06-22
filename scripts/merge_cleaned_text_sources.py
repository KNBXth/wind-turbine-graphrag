from pathlib import Path
import json
import hashlib
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
import sys

from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import config

# ========= 1. 路径配置 =========
BASE_DIR = config.BASE_DIR

# text 类型清洗结果父目录（递归读取其下所有 json）
TEXT_CLEAN_ROOT = config.CLEANED_TEXT_DIR

# OCR 清洗结果目录（读取其下所有 jsonl）
OCR_CLEAN_DIR = config.OCR_CLEANED_DIR

# 输出目录
OUTPUT_DIR = config.MERGED_TEXT_DIR
DOC_OUTPUT_DIR = OUTPUT_DIR / "docs"
DOC_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

INDEX_OUTPUT_PATH = OUTPUT_DIR / "merged_docs.jsonl"

# ========= 2. 合并策略 =========
# 页级来源优先级：text_clean > ocr_clean
SOURCE_PRIORITY = {
    "text_clean": 1,
    "native_clean": 1,
    "ocr_clean": 2,
    "unknown": 99,
}

# 是否在 merged_text 中加入页标记
ADD_PAGE_MARKERS = True

# text 类型中，目录页是否写入 merged_text
# 通常建议 False，这样后续 chunk 更干净
INCLUDE_TOC_IN_MERGED_TEXT = False

# OCR 中被标记为过滤页时，是否仍允许作为候选回退页
ALLOW_FILTERED_OCR_AS_FALLBACK = True


# ========= 3. 通用工具 =========
def normalize_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x).strip()


def make_doc_id(relative_path: str, file_name: str) -> str:
    base = relative_path or file_name or "unknown_doc"
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:12]


def infer_title(file_name: str, relative_path: str = "") -> str:
    """
    简单标题推断：
    优先用 file_name 去掉 .pdf
    """
    name = file_name or Path(relative_path).name
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    return name.strip()


def save_json(obj: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def save_jsonl(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def get_source_priority(source_name: str) -> int:
    return SOURCE_PRIORITY.get(source_name, SOURCE_PRIORITY["unknown"])


def build_doc_key(relative_path: str, file_name: str) -> str:
    """
    文档对齐键：
    优先 relative_path，其次 file_name
    """
    relative_path = normalize_str(relative_path)
    file_name = normalize_str(file_name)

    if relative_path:
        return f"rel::{relative_path}"
    if file_name:
        return f"name::{file_name}"
    return "unknown"


# ========= 4. 统一标准字段构造 =========
def build_standard_merged_doc(
    relative_path: str,
    file_name: str,
    merged_pages: List[Dict[str, Any]],
    merged_text: str,
    selected_source_stats: Dict[str, int],
    has_text_clean: bool,
    has_ocr_clean: bool,
    doc_type: str = "standard",
) -> Dict[str, Any]:
    doc_id = make_doc_id(relative_path, file_name)
    title = infer_title(file_name, relative_path)

    normalized_pages = []
    for page in merged_pages:
        normalized_pages.append({
            "page_num": int(page.get("page_num", 0)),
            "selected_source": normalize_str(page.get("selected_source", "unknown")),
            "text": normalize_str(page.get("text", "")),
            "is_toc_page": bool(page.get("is_toc_page", False)),
            "is_filtered": bool(page.get("is_filtered", False)),
            "filter_reason": normalize_str(page.get("filter_reason", "")),
        })

    merged_doc = {
        "doc_id": doc_id,
        "file_name": normalize_str(file_name),
        "relative_path": normalize_str(relative_path),
        "title": title,
        "doc_type": doc_type,
        "source_summary": {
            "has_text_clean": has_text_clean,
            "has_ocr_clean": has_ocr_clean,
            "selected_source_stats": dict(selected_source_stats),
        },
        "page_count": len(normalized_pages),
        "merged_text": normalize_str(merged_text),
        "pages": normalized_pages,
    }
    return merged_doc


def build_merged_doc_index_row(merged_doc: Dict[str, Any], merged_doc_path: Path) -> Dict[str, Any]:
    return {
        "doc_id": merged_doc["doc_id"],
        "title": merged_doc["title"],
        "file_name": merged_doc["file_name"],
        "relative_path": merged_doc["relative_path"],
        "doc_type": merged_doc["doc_type"],
        "page_count": merged_doc["page_count"],
        "merged_text_len": len(merged_doc.get("merged_text", "")),
        "selected_source_stats": merged_doc.get("source_summary", {}).get("selected_source_stats", {}),
        "merged_doc_path": str(merged_doc_path),
    }


# ========= 5. 文件收集 =========
def collect_text_clean_files() -> List[Path]:
    if not TEXT_CLEAN_ROOT.exists():
        print(f"[WARN] text 清洗目录不存在: {TEXT_CLEAN_ROOT}")
        return []

    files = []
    for p in TEXT_CLEAN_ROOT.rglob("*.json"):
        if "ocr_pdf" in p.parts:
            continue
        files.append(p)

    return sorted(files)


def collect_ocr_clean_files() -> List[Path]:
    if not OCR_CLEAN_DIR.exists():
        print(f"[WARN] OCR 清洗目录不存在: {OCR_CLEAN_DIR}")
        return []
    return sorted(OCR_CLEAN_DIR.rglob("*.jsonl"))


# ========= 6. 读取 text 清洗结果 =========
def load_text_clean_json(path: Path) -> Optional[Dict[str, Any]]:
    """
    text 类型清洗结果结构示例：
    {
      "file_name": "...pdf",
      "relative_path": "...pdf",
      "cleaned_pages": [
        {"page_num":1,"is_toc_page":false,"text":"..."}
      ],
      "cleaned_full_text": "..."
    }
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if "cleaned_pages" not in data:
            return None
        return data
    except Exception:
        return None


# ========= 7. 读取 OCR 清洗结果 =========
def load_ocr_clean_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except Exception:
                    continue
    except Exception:
        return []
    return rows


# ========= 8. 构建文档池 =========
def build_document_pool(
    text_files: List[Path],
    ocr_files: List[Path]
) -> Dict[str, Dict[str, Any]]:
    """
    输出结构：
    {
      doc_key: {
        "relative_path": ...,
        "file_name": ...,
        "doc_id": ...,
        "text_doc": {...} | None,
        "ocr_pages": {
            1: [row1, row2],
            2: [...]
        }
      }
    }
    """
    docs: Dict[str, Dict[str, Any]] = {}

    # ---- text clean ----
    for path in tqdm(text_files, desc="读取 text 清洗结果"):
        data = load_text_clean_json(path)
        if not data:
            continue

        relative_path = normalize_str(data.get("relative_path"))
        file_name = normalize_str(data.get("file_name"))
        doc_key = build_doc_key(relative_path, file_name)

        if doc_key not in docs:
            docs[doc_key] = {
                "relative_path": relative_path,
                "file_name": file_name,
                "doc_id": make_doc_id(relative_path, file_name),
                "text_doc": None,
                "ocr_pages": defaultdict(list),
            }

        docs[doc_key]["text_doc"] = data

        if not docs[doc_key]["relative_path"] and relative_path:
            docs[doc_key]["relative_path"] = relative_path
        if not docs[doc_key]["file_name"] and file_name:
            docs[doc_key]["file_name"] = file_name

    # ---- ocr clean ----
    for path in tqdm(ocr_files, desc="读取 OCR 清洗结果"):
        rows = load_ocr_clean_jsonl(path)
        if not rows:
            continue

        for row in rows:
            relative_path = normalize_str(row.get("relative_path"))
            file_name = normalize_str(row.get("file_name"))
            doc_key = build_doc_key(relative_path, file_name)

            if doc_key not in docs:
                docs[doc_key] = {
                    "relative_path": relative_path,
                    "file_name": file_name,
                    "doc_id": make_doc_id(relative_path, file_name),
                    "text_doc": None,
                    "ocr_pages": defaultdict(list),
                }

            if not docs[doc_key]["relative_path"] and relative_path:
                docs[doc_key]["relative_path"] = relative_path
            if not docs[doc_key]["file_name"] and file_name:
                docs[doc_key]["file_name"] = file_name

            try:
                page_num = int(row.get("page_num", 0))
            except Exception:
                page_num = 0

            if page_num <= 0:
                continue

            docs[doc_key]["ocr_pages"][page_num].append(row)

    return docs


# ========= 9. OCR 页级选择 =========
def choose_best_ocr_page(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    OCR 页优先级：
    1. 未过滤页优先
    2. 文本更长优先
    """
    if not rows:
        return None

    def score(row: Dict[str, Any]):
        filtered_flag = 1 if bool(row.get("is_filtered", False)) else 0
        text = normalize_str(row.get("clean_text") or row.get("text"))
        text_len = len(text)
        return (filtered_flag, -text_len)

    sorted_rows = sorted(rows, key=score)

    # 优先未过滤且有文本
    for row in sorted_rows:
        text = normalize_str(row.get("clean_text") or row.get("text"))
        if text and not bool(row.get("is_filtered", False)):
            return row

    # 再退回过滤页（如果允许）
    if ALLOW_FILTERED_OCR_AS_FALLBACK:
        for row in sorted_rows:
            text = normalize_str(row.get("clean_text") or row.get("text"))
            if text:
                return row

    return None


# ========= 10. 合并单个文档 =========
def merge_one_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    relative_path = normalize_str(doc.get("relative_path"))
    file_name = normalize_str(doc.get("file_name"))
    text_doc = doc.get("text_doc")
    ocr_pages_map = doc.get("ocr_pages", {})

    has_text_clean = text_doc is not None
    has_ocr_clean = len(ocr_pages_map) > 0

    page_num_set = set()

    # text 页
    if text_doc:
        for p in text_doc.get("cleaned_pages", []):
            try:
                page_num_set.add(int(p.get("page_num", 0)))
            except Exception:
                pass

    # ocr 页
    page_num_set.update(ocr_pages_map.keys())

    page_nums = sorted([p for p in page_num_set if p > 0])

    merged_pages: List[Dict[str, Any]] = []
    merged_text_parts: List[str] = []
    selected_source_stats = defaultdict(int)

    # 为了加速 text 页匹配，先建索引
    text_page_index = {}
    if text_doc:
        for p in text_doc.get("cleaned_pages", []):
            try:
                pn = int(p.get("page_num", 0))
            except Exception:
                continue
            if pn > 0:
                text_page_index[pn] = p

    for page_num in page_nums:
        selected_source = "unknown"
        selected_text = ""
        is_toc_page = False
        is_filtered = False
        filter_reason = ""

        # 1) 优先选 text_clean
        text_page = text_page_index.get(page_num)
        if text_page:
            page_text = normalize_str(text_page.get("text"))
            if page_text:
                selected_source = "text_clean"
                selected_text = page_text
                is_toc_page = bool(text_page.get("is_toc_page", False))

        # 2) 如果没有 text，再回退 OCR
        if not selected_text:
            best_ocr = choose_best_ocr_page(ocr_pages_map.get(page_num, []))
            if best_ocr:
                page_text = normalize_str(best_ocr.get("clean_text") or best_ocr.get("text"))
                if page_text:
                    selected_source = "ocr_clean"
                    selected_text = page_text
                    is_filtered = bool(best_ocr.get("is_filtered", False))
                    filter_reason = normalize_str(best_ocr.get("filter_reason", ""))

        # 3) 仍无文本
        if not selected_text:
            selected_source = "empty"

        selected_source_stats[selected_source] += 1

        merged_pages.append({
            "page_num": page_num,
            "selected_source": selected_source,
            "text": selected_text,
            "is_toc_page": is_toc_page,
            "is_filtered": is_filtered,
            "filter_reason": filter_reason,
        })

        # 拼 merged_text
        if not selected_text:
            continue

        # text 目录页默认不拼进 merged_text
        if selected_source == "text_clean" and is_toc_page and not INCLUDE_TOC_IN_MERGED_TEXT:
            continue

        if ADD_PAGE_MARKERS:
            merged_text_parts.append(f"\n\n[PAGE {page_num}]\n{selected_text}")
        else:
            merged_text_parts.append(selected_text)

    merged_text = "\n".join(x.strip() for x in merged_text_parts if x.strip()).strip()

    merged_doc = build_standard_merged_doc(
        relative_path=relative_path,
        file_name=file_name,
        merged_pages=merged_pages,
        merged_text=merged_text,
        selected_source_stats=dict(selected_source_stats),
        has_text_clean=has_text_clean,
        has_ocr_clean=has_ocr_clean,
        doc_type="standard",
    )

    return merged_doc


# ========= 11. 主流程 =========
def main():
    text_files = collect_text_clean_files()
    ocr_files = collect_ocr_clean_files()

    print(f"[INFO] text 清洗文件数: {len(text_files)}")
    print(f"[INFO] OCR 清洗文件数: {len(ocr_files)}")
    print(f"待合并输入文件数: {len(text_files) + len(ocr_files)}")

    if not text_files and not ocr_files:
        print("未找到可合并文件。")
        return

    docs = build_document_pool(text_files, ocr_files)
    print(f"识别到文档数: {len(docs)}")

    merged_index_rows: List[Dict[str, Any]] = []

    for _, doc in tqdm(docs.items(), desc="合并文档"):
        merged_doc = merge_one_doc(doc)

        out_path = DOC_OUTPUT_DIR / f"{merged_doc['doc_id']}.json"
        save_json(merged_doc, out_path)

        index_row = build_merged_doc_index_row(merged_doc, out_path)
        merged_index_rows.append(index_row)

    save_jsonl(merged_index_rows, INDEX_OUTPUT_PATH)

    print("\n合并完成。")
    print(f"输出文档目录: {DOC_OUTPUT_DIR}")
    print(f"合并索引文件: {INDEX_OUTPUT_PATH}")
    print(f"共输出文档数: {len(merged_index_rows)}")


if __name__ == "__main__":
    main()