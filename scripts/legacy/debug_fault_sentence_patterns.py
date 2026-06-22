from pathlib import Path
import ast
import json
import random


SOURCE_SCRIPT = Path(r"E:\WORK\data\scripts\extract_entities_relations_v3_1.py")
CHUNKS_DIR = Path(r"E:\WORK\data\chunks")

MIN_SAMPLE_SIZE = 30
MAX_SAMPLE_SIZE = 60
RANDOM_SEED = 42


REUSED_CONSTANTS = {
    "STANDARD_PATTERNS",
    "DEVICE_TERMS",
    "PARAMETER_TERMS",
    "METHOD_TERMS",
    "CONDITION_TERMS",
    "ACTION_TERMS",
    "COMPONENT_TERMS",
    "FAULT_TERMS",
    "SYMPTOM_TERMS",
    "CAUSE_TERMS",
    "MAINTENANCE_ACTION_TERMS",
}

REUSED_FUNCTIONS = {
    "normalize_text",
    "find_standard_entities",
    "find_term_entities",
    "unique_entities",
    "extract_entities_from_text",
    "split_sentences",
}


def load_extractor_symbols(script_path: Path):
    """
    只加载词表和实体抽取函数，不执行原脚本主流程。
    """
    source = script_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(script_path))

    selected_nodes = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            selected_nodes.append(node)
            continue

        if isinstance(node, ast.Assign):
            names = []
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.append(target.id)
            if any(name in REUSED_CONSTANTS for name in names):
                selected_nodes.append(node)
            continue

        if isinstance(node, ast.FunctionDef) and node.name in REUSED_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    code = compile(module, filename=str(script_path), mode="exec")
    namespace = {}
    exec(code, namespace)
    return namespace


def sentence_pairs(sent: str, entities: list, right_type: str):
    faults = [e for e in entities if e.get("entity_type") == "Fault"]
    rights = [e for e in entities if e.get("entity_type") == right_type]

    pairs = []
    for f in faults:
        fault_name = f.get("entity_name", "")
        if not fault_name or fault_name not in sent:
            continue
        for r in rights:
            right_name = r.get("entity_name", "")
            if not right_name or right_name not in sent:
                continue
            pairs.append((fault_name, right_name))
    return pairs


def collect_candidates(chunks_dir: Path, extract_entities_from_text, split_sentences):
    fault_cause_rows = []
    fault_symptom_rows = []

    for file_path in chunks_dir.rglob("*.jsonl"):
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except Exception:
                    continue

                text = chunk.get("text", "")
                if not text:
                    continue

                file_name = chunk.get("file_name", "")
                page_num = chunk.get("page_num", "")
                page_span = chunk.get("page_span", "")
                chunk_id = chunk.get("chunk_id", "")
                doc_id = chunk.get("doc_id", "")

                for sent in split_sentences(text):
                    entities = extract_entities_from_text(sent)
                    if len(entities) < 2:
                        continue

                    cause_pairs = sentence_pairs(sent, entities, "Cause")
                    for fault_name, cause_name in cause_pairs:
                        fault_cause_rows.append({
                            "sent": sent,
                            "fault": fault_name,
                            "cause": cause_name,
                            "file_name": file_name,
                            "page_num": page_num,
                            "page_span": page_span,
                            "chunk_id": chunk_id,
                            "doc_id": doc_id
                        })

                    symptom_pairs = sentence_pairs(sent, entities, "Symptom")
                    for fault_name, symptom_name in symptom_pairs:
                        fault_symptom_rows.append({
                            "sent": sent,
                            "fault": fault_name,
                            "symptom": symptom_name,
                            "file_name": file_name,
                            "page_num": page_num,
                            "page_span": page_span,
                            "chunk_id": chunk_id,
                            "doc_id": doc_id
                        })

    return fault_cause_rows, fault_symptom_rows


def dedup_rows(rows: list, right_key: str):
    seen = set()
    result = []
    for r in rows:
        key = (
            r.get("sent", ""),
            r.get("fault", ""),
            r.get(right_key, ""),
            r.get("file_name", ""),
            str(r.get("page_num", "")),
            str(r.get("page_span", "")),
        )
        if key not in seen:
            result.append(r)
            seen.add(key)
    return result


def sample_rows(rows: list, min_n: int = MIN_SAMPLE_SIZE, max_n: int = MAX_SAMPLE_SIZE):
    if not rows:
        return []
    n = min(len(rows), max(max_n, min_n))
    n = max(min_n, n) if len(rows) >= min_n else len(rows)
    return random.sample(rows, n) if len(rows) > n else rows


def print_samples(title: str, rows: list, right_key: str):
    print("\n" + "=" * 80)
    print(f"{title} | 样本数: {len(rows)}")
    print("=" * 80)
    for idx, r in enumerate(rows, start=1):
        print(f"[{idx}] fault={r.get('fault', '')} | {right_key}={r.get(right_key, '')}")
        print(f"     file_name={r.get('file_name', '')}")
        print(f"     page_num={r.get('page_num', '')} | page_span={r.get('page_span', '')}")
        print(f"     sent={r.get('sent', '')}")
        print("-" * 80)


def main():
    if not SOURCE_SCRIPT.exists():
        raise FileNotFoundError(f"未找到源脚本: {SOURCE_SCRIPT}")
    if not CHUNKS_DIR.exists():
        raise FileNotFoundError(f"未找到 chunks 目录: {CHUNKS_DIR}")

    random.seed(RANDOM_SEED)

    symbols = load_extractor_symbols(SOURCE_SCRIPT)
    extract_entities_from_text = symbols["extract_entities_from_text"]
    split_sentences = symbols["split_sentences"]

    fault_cause_rows, fault_symptom_rows = collect_candidates(
        CHUNKS_DIR,
        extract_entities_from_text=extract_entities_from_text,
        split_sentences=split_sentences
    )

    fault_cause_rows = dedup_rows(fault_cause_rows, right_key="cause")
    fault_symptom_rows = dedup_rows(fault_symptom_rows, right_key="symptom")

    cause_samples = sample_rows(fault_cause_rows, min_n=MIN_SAMPLE_SIZE, max_n=MAX_SAMPLE_SIZE)
    symptom_samples = sample_rows(fault_symptom_rows, min_n=MIN_SAMPLE_SIZE, max_n=MAX_SAMPLE_SIZE)

    print(f"Fault-Cause 候选总数: {len(fault_cause_rows)}")
    print(f"Fault-Symptom 候选总数: {len(fault_symptom_rows)}")

    print_samples("Fault + Cause 候选句", cause_samples, right_key="cause")
    print_samples("Fault + Symptom 候选句", symptom_samples, right_key="symptom")


if __name__ == "__main__":
    main()
