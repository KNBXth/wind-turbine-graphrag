from db import run_query
import logging
from mappings import (
    ENTITY_ALIAS_MAP,
    QUESTION_PATTERNS,
    RELATION_SCORE_HINTS,
    QUESTION_RELATION_FILTER_WORDS,
    MAX_QA_RESULTS,
    FAULT_QA_PATTERNS,
    FAULT_RELATION_SCORE_HINTS,
)

logger = logging.getLogger(__name__)
from services.graph_service import (
    deduplicate_records,
    normalize_entity_name,
)


def has_page_info(row: dict) -> bool:
    page_span = row.get("page_span")
    page_num = row.get("page_num")
    return page_span not in (None, "") or page_num not in (None, "")


def detect_question_type(question: str) -> str:
    q = question.strip()

    if any(x in q for x in QUESTION_PATTERNS["使用方法"]):
        return "使用方法"
    if any(x in q for x in QUESTION_PATTERNS["参数要求"]):
        return "参数要求"
    if any(x in q for x in QUESTION_PATTERNS["条件约束"]):
        return "条件约束"
    if any(x in q for x in QUESTION_PATTERNS["措施要求"]):
        return "措施要求"

    return ""


def extract_entity_from_question(question: str, query_type: str) -> str:
    q = question.strip()

    patterns = QUESTION_PATTERNS.get(query_type, [])
    entity_name = q
    for p in patterns:
        entity_name = entity_name.replace(p, "")

    entity_name = entity_name.replace("有哪些", "").replace("有什么", "")
    entity_name = entity_name.replace("在什么", "").replace("需要什么", "").replace("需要哪些", "")
    entity_name = entity_name.strip("？? ：:，,。 ")

    return normalize_entity_name(entity_name)


def detect_fault_question_type(question: str) -> str:
    q = question.strip()

    if any(x in q for x in FAULT_QA_PATTERNS["部件故障"]):
        return "部件故障"
    if any(x in q for x in FAULT_QA_PATTERNS["故障症状"]):
        return "故障症状"
    if any(x in q for x in FAULT_QA_PATTERNS["故障原因"]):
        return "故障原因"
    if any(x in q for x in FAULT_QA_PATTERNS["处理措施"]):
        return "处理措施"
    if any(x in q for x in FAULT_QA_PATTERNS["检测方法"]):
        return "检测方法"

    return ""


def extract_fault_entity_from_question(question: str, query_type: str) -> str:
    q = question.strip()
    patterns = FAULT_QA_PATTERNS.get(query_type, [])

    entity_name = q
    for p in patterns:
        entity_name = entity_name.replace(p, "")

    entity_name = (
        entity_name.replace("的", "")
                   .replace("可能", "")
                   .replace("应", "")
                   .replace("维护", "")
                   .strip("？? ：:，,。 ")
    )

    return normalize_entity_name(entity_name)


def score_record(row: dict, entity_name: str, query_type: str) -> int:
    score = 0
    text = (row.get("source_sentence") or "").strip()
    target_name = row.get("target_name", "")
    file_name = row.get("file_name", "") or ""

    if entity_name and entity_name in text:
        score += 4
    if target_name and target_name in text:
        score += 3

    for hint in RELATION_SCORE_HINTS.get(query_type, []):
        if hint in text:
            score += 2

    for good_hint in ["标准", "规范", "规程", "监督", "技术"]:
        if good_hint in file_name:
            score += 1
            break

    if has_page_info(row):
        score += 1

    if len(text) < 12:
        score -= 2

    if not any(w in text for w in QUESTION_RELATION_FILTER_WORDS.get(query_type, [])):
        score -= 3

    if query_type == "参数要求":
        if not any(w in text for w in ["应满足", "应符合", "不超过", "不低于", "限值", "误差", "温升"]):
            score -= 1

    if query_type == "条件约束":
        if not any(w in text for w in ["条件", "环境温度", "相对湿度", "海拔", "户内", "户外", "运行条件"]):
            score -= 1

    if query_type == "措施要求":
        if not any(w in text for w in ["应采取", "应进行", "加强监测", "更换", "维修", "检修", "停运", "整改"]):
            score -= 1

    return score


def sort_and_deduplicate_qa_records(records, query_type, entity_name):
    if not records:
        return []

    for row in records:
        row["_score"] = score_record(row, entity_name, query_type)

    records = sorted(records, key=lambda x: x.get("_score", 0), reverse=True)
    filtered = [r for r in records if r.get("_score", 0) >= 3]

    if not filtered:
        filtered = records[:10]

    deduped = deduplicate_records(
        filtered,
        group_keys=["source_name", "relation_en", "target_name"]
    )

    return deduped[:MAX_QA_RESULTS]


def generate_answer_summary(entity_name: str, query_type: str, results: list) -> str:
    if not results:
        return "未检索到与该问题直接匹配的图谱结果。"

    top_items = [r["target_name"] for r in results[:5]]
    item_text = "、".join(top_items)

    if query_type == "使用方法":
        return f"根据图谱证据，{entity_name}相关的主要使用方法包括：{item_text}。"
    elif query_type == "参数要求":
        return f"根据图谱证据，{entity_name}相关的主要参数要求包括：{item_text}。"
    elif query_type == "条件约束":
        return f"根据图谱证据，{entity_name}相关的主要条件约束包括：{item_text}。"
    elif query_type == "措施要求":
        return f"根据图谱证据，{entity_name}相关的主要措施要求包括：{item_text}。"

    return f"根据图谱检索结果，{entity_name}匹配到 {len(results)} 条相关结果。"


def score_fault_record(row: dict, entity_name: str, query_type: str) -> int:
    score = 0
    text = (row.get("source_sentence") or "").strip()
    target_name = row.get("target_name", "")
    file_name = row.get("file_name", "") or ""

    if entity_name and entity_name in text:
        score += 4
    if target_name and target_name in text:
        score += 3

    for hint in FAULT_RELATION_SCORE_HINTS.get(query_type, []):
        if hint in text:
            score += 2

    for good_hint in ["标准", "规范", "规程", "监督", "技术"]:
        if good_hint in file_name:
            score += 1
            break

    if has_page_info(row):
        score += 1

    if len(text) < 10:
        score -= 2

    return score


def sort_and_deduplicate_fault_records(records, query_type, entity_name):
    if not records:
        return []

    for row in records:
        row["_score"] = score_fault_record(row, entity_name, query_type)

    records = sorted(records, key=lambda x: x.get("_score", 0), reverse=True)
    filtered = [r for r in records if r.get("_score", 0) >= 3]

    if not filtered:
        filtered = records[:10]

    deduped = deduplicate_records(
        filtered,
        group_keys=["source_name", "relation_en", "target_name"]
    )

    return deduped[:6]


def generate_fault_answer_summary(entity_name: str, query_type: str, results: list) -> str:
    if not results:
        return "未检索到与该故障/部件问题直接匹配的图谱结果。"

    top_items = [r["target_name"] for r in results[:5]]
    item_text = "、".join(top_items)

    if query_type == "部件故障":
        return f"根据图谱证据，{entity_name}相关的主要故障包括：{item_text}。"
    elif query_type == "故障症状":
        return f"根据图谱证据，{entity_name}相关的主要症状包括：{item_text}。"
    elif query_type == "故障原因":
        return f"根据图谱证据，{entity_name}可能的主要原因包括：{item_text}。"
    elif query_type == "处理措施":
        return f"根据图谱证据，针对{entity_name}可采取的主要处理措施包括：{item_text}。"
    elif query_type == "检测方法":
        return f"根据图谱证据，{entity_name}相关的主要检测方法包括：{item_text}。"

    return f"根据图谱检索结果，{entity_name}匹配到 {len(results)} 条相关结果。"


def qa_query(question: str):
    try:
        q = question.strip()

        # A. 故障问答
        fault_query_type = detect_fault_question_type(q)
        if fault_query_type:
            entity_name = extract_fault_entity_from_question(q, fault_query_type)

            if not entity_name:
                return "", fault_query_type, [], "未识别到明确的查询实体。"

            if fault_query_type == "部件故障":
                query = """
            MATCH (f:Entity)-[r:OCCURS_ON]->(c:Entity {name: $entity_name})
            RETURN
                c.name AS source_name,
                c.type AS source_type,
                coalesce(r.rel_zh, "") AS relation_zh,
                type(r) AS relation_en,
                f.name AS target_name,
                f.type AS target_type,
                r.file_name AS file_name,
                r.page_num AS page_num,
                r.page_span AS page_span,
                r.source_sentence AS source_sentence
            LIMIT 300
            """
                raw_records = run_query(query, {"entity_name": entity_name})
                results = sort_and_deduplicate_fault_records(raw_records, fault_query_type, entity_name)
                summary = generate_fault_answer_summary(entity_name, fault_query_type, results)
                return entity_name, fault_query_type, results, summary

            relation_map = {
                "故障症状": "HAS_SYMPTOM",
                "故障原因": "CAUSED_BY",
                "处理措施": "RESOLVED_BY",
                "检测方法": "DETECTED_BY"
            }

            relation_type = relation_map.get(fault_query_type, "")
            if not relation_type:
                return entity_name, fault_query_type, [], "当前故障问题类型暂不支持。"

            query = f"""
        MATCH (n:Entity {{name: $entity_name}})-[r:{relation_type}]->(m:Entity)
        RETURN
            n.name AS source_name,
            n.type AS source_type,
            coalesce(r.rel_zh, "") AS relation_zh,
            type(r) AS relation_en,
            m.name AS target_name,
            m.type AS target_type,
            r.file_name AS file_name,
            r.page_num AS page_num,
            r.page_span AS page_span,
            r.source_sentence AS source_sentence
        LIMIT 300
        """
            raw_records = run_query(query, {"entity_name": entity_name})
            results = sort_and_deduplicate_fault_records(raw_records, fault_query_type, entity_name)
            summary = generate_fault_answer_summary(entity_name, fault_query_type, results)
            return entity_name, fault_query_type, results, summary

        # B. 普通标准问答
        query_type = detect_question_type(q)

        if not query_type:
            return "", "", [], "未识别到明确的问题类型。"

        entity_name = extract_entity_from_question(q, query_type)

        if not entity_name:
            return "", query_type, [], "未识别到明确的查询实体。"

        relation_map = {
            "使用方法": "USES_METHOD",
            "参数要求": "HAS_PARAMETER",
            "条件约束": "UNDER_CONDITION",
            "措施要求": "REQUIRES_ACTION"
        }

        relation_type = relation_map.get(query_type, "")
        if not relation_type:
            return entity_name, query_type, [], "当前问题类型暂不支持。"

        query = f"""
    MATCH (n:Entity {{name: $entity_name}})-[r:{relation_type}]->(m:Entity)
    RETURN
        n.name AS source_name,
        n.type AS source_type,
        coalesce(r.rel_zh, "") AS relation_zh,
        type(r) AS relation_en,
        m.name AS target_name,
        m.type AS target_type,
        r.file_name AS file_name,
        r.page_num AS page_num,
        r.page_span AS page_span,
        r.source_sentence AS source_sentence
    LIMIT 300
    """

        raw_records = run_query(query, {"entity_name": entity_name})
        results = sort_and_deduplicate_qa_records(raw_records, query_type, entity_name)
        summary = generate_answer_summary(entity_name, query_type, results)

        return entity_name, query_type, results, summary
    except Exception:
        logger.exception("qa_query 执行异常。question=%s", question)
        return "", "", [], "问答查询失败，请检查 Neo4j 连接和图谱数据状态。"