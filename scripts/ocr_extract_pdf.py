from pathlib import Path
import os
import io
import json
import hashlib
from typing import List, Dict, Any, Optional
import re
import sys
# ========= 0. 运行环境兼容设置 =========
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import fitz  # PyMuPDF
import numpy as np
import pandas as pd
from tqdm import tqdm
from PIL import Image
from paddleocr import PaddleOCR

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import config

# ========= 1. 路径配置 =========
RAW_PDF_DIR = config.RAW_PDF_DIR
OUTPUT_DIR = config.OCR_EXTRACTED_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PDF_INVENTORY_CSV = config.PDF_INVENTORY_CSV

# ========= 2. OCR 配置（PaddleOCR 2.7.3 稳定版） =========
OCR = PaddleOCR(
    use_angle_cls=True,
    lang="ch",
    use_gpu=False,
)

# ========= 3. 运行参数 =========
# PDF 渲染分辨率；1.5 通常是速度与效果的折中
ZOOM_X = 1.5
ZOOM_Y = 1.5

# 只调试第一页
DEBUG_FIRST_PAGE = False

# 每个 PDF 最多处理多少页
# None = 全页；调试时可改成 3
MAX_PAGES_PER_PDF: Optional[int] = None

# 最多处理多少个 PDF
# None = 全部；调试时可改成 5 或 10
LIMIT_PDF_COUNT: Optional[int] = None

# 是否在结束时等待回车，方便看统计
WAIT_AT_END = True


# ========= 4. 工具函数 =========
def make_doc_id(path_str: str) -> str:
    return hashlib.md5(path_str.encode("utf-8")).hexdigest()[:12]


def safe_relative_path(pdf_path: Path, root_dir: Path) -> Path:
    """
    尽量返回相对于 RAW_PDF_DIR 的路径；
    如果失败，则退回文件名，避免异常中断。
    """
    try:
        return pdf_path.relative_to(root_dir)
    except Exception:
        return Path(pdf_path.name)


def load_scanned_pdf_paths() -> List[Path]:
    """
    读取 pdf_inventory.csv，
    只返回 detect_status 成功 且 is_scanned_suspect=True 的 PDF。
    """
    if not PDF_INVENTORY_CSV.exists():
        print("[WARN] pdf_inventory.csv 不存在，将退回到全量 PDF 扫描。")
        return list(RAW_PDF_DIR.rglob("*.pdf"))

    df = pd.read_csv(PDF_INVENTORY_CSV)

    required_cols = ["full_path", "is_scanned_suspect", "detect_status"]
    for col in required_cols:
        if col not in df.columns:
            print(f"[WARN] pdf_inventory.csv 缺少字段: {col}，将退回到全量 PDF 扫描。")
            return list(RAW_PDF_DIR.rglob("*.pdf"))

    scanned_paths = []

    for _, row in df.iterrows():
        detect_status = str(row.get("detect_status", "")).strip().lower()
        is_scanned = row.get("is_scanned_suspect", False)
        full_path = str(row.get("full_path", "")).strip()

        if isinstance(is_scanned, str):
            is_scanned = is_scanned.strip().lower() in {"true", "1", "yes"}

        if detect_status.startswith("success") and is_scanned and full_path:
            pdf_path = Path(full_path)
            if pdf_path.exists():
                scanned_paths.append(pdf_path)

    scanned_paths = list(dict.fromkeys(scanned_paths))

    print(f"[INFO] 从 pdf_inventory.csv 中识别到疑似扫描件数量: {len(scanned_paths)}")
    print("[INFO] 前 10 个待 OCR 文件：")
    for p in scanned_paths[:10]:
        print("  ", p)

    return scanned_paths


def render_page_to_image(page, zoom_x=1.5, zoom_y=1.5):
    """
    将 PDF 页面渲染为像素图
    """
    mat = fitz.Matrix(zoom_x, zoom_y)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix


def ocr_page_image(pix) -> Dict[str, Any]:
    """
    对一页图片做 OCR（PaddleOCR 2.7.3）
    返回：
    {
        "text": "...",
        "avg_conf": 0.93,
        "line_count": 20,
        "error": None
    }
    """
    try:
        img_bytes = pix.tobytes("png")
        image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img_np = np.array(image)

        result = OCR.ocr(img_np, cls=True)

        lines = []
        confs = []

        # PaddleOCR 2.x 常见返回格式：
        # [
        #   [
        #       [box, (text, conf)],
        #       ...
        #   ]
        # ]
        if result and isinstance(result, list):
            for block in result:
                if not block:
                    continue
                if isinstance(block, list):
                    for item in block:
                        try:
                            text = item[1][0].strip()
                            conf = float(item[1][1])
                        except Exception:
                            continue
                        if text:
                            lines.append(text)
                            confs.append(conf)

        page_text = "\n".join(lines).strip()
        avg_conf = sum(confs) / len(confs) if confs else 0.0

        return {
            "text": page_text,
            "avg_conf": round(avg_conf, 4),
            "line_count": len(lines),
            "error": None
        }

    except Exception as e:
        return {
            "text": "",
            "avg_conf": 0.0,
            "line_count": 0,
            "error": f"ocr_failed: {e}"
        }


def count_existing_output_lines(output_path: Path) -> int:
    """
    统计已有 jsonl 输出的有效行数
    """
    with open(output_path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def make_safe_filename(name: str, max_len: int = 80) -> str:
    """
    把文件名清洗成适合 Windows 保存的形式
    """
    name = name.strip()

    # 去掉扩展名
    name = re.sub(r"\.pdf$", "", name, flags=re.IGNORECASE)

    # 替换 Windows 非法字符
    name = re.sub(r'[<>:"/\\|?*]', "_", name)

    # 压缩空白
    name = re.sub(r"\s+", "_", name)

    # 连续下划线压缩
    name = re.sub(r"_+", "_", name)

    name = name.strip("._ ")

    if not name:
        name = "unknown_doc"

    if len(name) > max_len:
        name = name[:max_len].rstrip("._ ")

    return name

def process_one_pdf(pdf_path: Path) -> Dict[str, Any]:
    relative_path = safe_relative_path(pdf_path, RAW_PDF_DIR)
    doc_id = make_doc_id(str(relative_path))
    safe_stem = make_safe_filename(pdf_path.stem)
    output_path = OUTPUT_DIR / f"{safe_stem}__{doc_id}.jsonl"

    # ========= 1. 先检查 PDF 能否打开，并获取真实页数 =========
    try:
        doc = fitz.open(pdf_path)
        real_page_count = len(doc)
        doc.close()
    except Exception as e:
        return {
            "status": "open_failed",
            "pdf": str(relative_path),
            "error": str(e)
        }

    # 调试时按页数上限截断“应处理页数”
    target_page_count = real_page_count
    if MAX_PAGES_PER_PDF is not None:
        target_page_count = min(real_page_count, MAX_PAGES_PER_PDF)

    # ========= 2. 如果输出文件已存在，检查是否完整 =========
    if output_path.exists():
        try:
            existing_page_count = count_existing_output_lines(output_path)

            if existing_page_count == target_page_count:
                return {
                    "status": "skip_exists",
                    "pdf": str(relative_path),
                    "pages": existing_page_count,
                    "output": str(output_path)
                }
            else:
                print(
                    f"[WARN] 检测到不完整输出，重新处理: {relative_path} "
                    f"(已有 {existing_page_count} 页, 应处理 {target_page_count} 页)"
                )
                try:
                    output_path.unlink()
                except Exception:
                    pass

        except Exception as e:
            print(f"[WARN] 读取已有输出失败，准备重跑: {relative_path}, error={e}")
            try:
                output_path.unlink()
            except Exception:
                pass

    # ========= 3. 正式处理 PDF =========
    records = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return {
            "status": "open_failed",
            "pdf": str(relative_path),
            "error": str(e)
        }

    try:
        page_total = len(doc)
        if MAX_PAGES_PER_PDF is not None:
            page_total = min(page_total, MAX_PAGES_PER_PDF)

        for page_index in range(page_total):
            try:
                page = doc.load_page(page_index)
                pix = render_page_to_image(page, ZOOM_X, ZOOM_Y)
                ocr_result = ocr_page_image(pix)

                records.append({
                    "doc_id": doc_id,
                    "file_name": pdf_path.name,
                    "relative_path": str(relative_path),
                    "page_num": page_index + 1,
                    "text": ocr_result["text"],
                    "source_type": "ocr_scan_pdf",
                    "ocr_engine": "paddleocr 2.7.3",
                    "ocr_avg_conf": ocr_result["avg_conf"],
                    "ocr_line_count": ocr_result["line_count"],
                    "ocr_error": ocr_result.get("error")
                })

            except Exception as e:
                records.append({
                    "doc_id": doc_id,
                    "file_name": pdf_path.name,
                    "relative_path": str(relative_path),
                    "page_num": page_index + 1,
                    "text": "",
                    "source_type": "ocr_scan_pdf",
                    "ocr_engine": "paddleocr 2.7.3",
                    "ocr_avg_conf": 0.0,
                    "ocr_line_count": 0,
                    "ocr_error": f"page_process_failed: {e}"
                })

    finally:
        doc.close()

    # ========= 4. 写出结果 =========
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            for row in records:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:
        return {
            "status": "write_failed",
            "pdf": str(relative_path),
            "error": str(e)
        }

    return {
        "status": "ok",
        "pdf": str(relative_path),
        "pages": len(records),
        "output": str(output_path)
    }


def debug_one_pdf_first_page(pdf_path: Path):
    """
    只调试一个 PDF 的第一页，便于排查环境和识别效果
    """
    print(f"[DEBUG] 测试 PDF: {pdf_path}")

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"[DEBUG] 打开 PDF 失败: {e}")
        return

    try:
        if len(doc) == 0:
            print("[DEBUG] PDF 没有页面")
            return

        page = doc.load_page(0)
        pix = render_page_to_image(page, ZOOM_X, ZOOM_Y)
        result = ocr_page_image(pix)

        print("[DEBUG] OCR 测试结果：")
        print("error      =", result["error"])
        print("line_count =", result["line_count"])
        print("avg_conf   =", result["avg_conf"])
        print("text preview:")
        print(result["text"][:1000])

    finally:
        doc.close()


# ========= 5. 主流程 =========
def main():
    pdf_paths = load_scanned_pdf_paths()

    if LIMIT_PDF_COUNT is not None:
        pdf_paths = pdf_paths[:LIMIT_PDF_COUNT]
        print(f"[INFO] 已限制仅处理前 {len(pdf_paths)} 个 PDF")

    print(f"待 OCR 的 PDF 数量: {len(pdf_paths)}")
    if not pdf_paths:
        print("未找到需要 OCR 的扫描型 PDF。")
        return

    if DEBUG_FIRST_PAGE:
        debug_one_pdf_first_page(pdf_paths[0])
        return

    summary = {
        "ok": 0,
        "skip_exists": 0,
        "open_failed": 0,
        "write_failed": 0,
        "fatal_error": 0,
    }

    for pdf_path in tqdm(pdf_paths, desc="OCR 扫描型 PDF"):
        try:
            result = process_one_pdf(pdf_path)
            status = result.get("status", "fatal_error")
            summary[status] = summary.get(status, 0) + 1

            # 想看更详细过程可以打开这行
            # print(f"[INFO] {status}: {result.get('pdf', pdf_path)}")

        except Exception as e:
            print(f"[FATAL] 未捕获异常: {pdf_path}")
            print(f"[FATAL] error = {e}")
            summary["fatal_error"] = summary.get("fatal_error", 0) + 1

    print("=" * 60)
    print("OCR 提取完成。")
    print("统计：")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"OCR 输出目录: {OUTPUT_DIR}")
    print("=" * 60)

    if WAIT_AT_END:
        try:
            input("按回车退出...")
        except Exception:
            pass


if __name__ == "__main__":
    main()