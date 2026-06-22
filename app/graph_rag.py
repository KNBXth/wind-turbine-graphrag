from pathlib import Path
import json
import re
import logging
from collections import defaultdict

import config
from db import run_query
from services.llm_service import generate_answer_with_llm

logger = logging.getLogger(__name__)

# ========= 1. 数据文件路径（统一从 config 读取） =========
RELATIONS_FILE = config.RELATIONS_FILE

# ========= 2. 图谱关系中文映射 =========
RELATION_ZH_MAP = {
    "USES_METHOD": "使用方法",
    "HAS_PARAMETER": "参数要求",
    "UNDER_CONDITION": "条件约束",
    "REQUIRES_ACTION": "措施要求",
    "OCCURS_ON": "发生于部件",
    "HAS_SYMPTOM": "具有症状",
    "CAUSED_BY": "由原因引起",
    "RESOLVED_BY": "处理措施",
    "DETECTED_BY": "检测方法"
}

# ========= 3. 常见意图关键词 =========
QUESTION_HINTS = {
    "作用用途": ["作用", "用途", "功能", "是干什么的"],
    "定义说明": ["是什么", "什么意思", "定义"],
    "参数要求": ["参数", "指标", "要求"],
    "使用方法": ["方法", "怎么用", "如何用", "试验", "检测", "测量", "校验"],
    "条件约束": ["条件", "环境", "运行条件", "使用条件"],
    "措施要求": ["措施", "要求", "应采取什么措施"],
    "部件故障": ["有哪些故障", "有什么故障", "常见故障", "故障有哪些"],
    "故障症状": ["有哪些症状", "有什么症状", "症状有哪些", "故障症状"],
    "故障原因": ["什么原因引起", "可能由什么原因引起", "原因是什么", "故障原因"],
    "处理措施": ["怎么处理", "如何处理", "应采取什么维护措施", "应采取什么措施", "处理措施"],
    "检测方法": ["怎么检测", "如何检测", "通过什么方法检测", "检测方法是什么"]
}

GENERIC_ENTITY_TERMS = {
    "电压", "电流", "温度", "压力", "功率", "频率", "误差",
    "方法", "措施", "条件", "参数", "原因", "症状", "故障",
    "检测", "监测", "试验", "测量", "校验"
}

# ========= 4. 按意图约束关系类型 =========
INTENT_RELATION_FILTER = {
    "参数要求": {"HAS_PARAMETER"},
    "使用方法": {"USES_METHOD", "DETECTED_BY"},
    "条件约束": {"UNDER_CONDITION"},
    "措施要求": {"REQUIRES_ACTION"},
    "部件故障": {"OCCURS_ON"},
    "故障症状": {"HAS_SYMPTOM"},
    "故障原因": {"CAUSED_BY"},
    "处理措施": {"RESOLVED_BY", "REQUIRES_ACTION"},
    "检测方法": {"DETECTED_BY", "USES_METHOD"},
    # 作用用途、定义说明、综合查询 不做强关系限制
}

# ========= 5. 按意图约束目标实体类型 =========
INTENT_TARGET_TYPE_FILTER = {
    "参数要求": {"Parameter"},
    "使用方法": {"Method"},
    "条件约束": {"Condition"},
    "措施要求": {"Action", "MaintenanceAction"},
    "部件故障": {"Fault"},
    "故障症状": {"Symptom"},
    "故障原因": {"Cause"},
    "处理措施": {"Action", "MaintenanceAction"},
    "检测方法": {"Method"}
}

# ========= 6. 作用/定义类回答优先选用的关系 =========
GENERAL_INTENT_PRIORITY = [
    "HAS_PARAMETER",
    "USES_METHOD",
    "UNDER_CONDITION",
    "REQUIRES_ACTION",
    "OCCURS_ON",
    "HAS_SYMPTOM",
    "CAUSED_BY",
    "RESOLVED_BY",
    "DETECTED_BY"
]

# ========= 7. 工具函数 =========
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def get_page_display(row: dict) -> str:
    page_span = row.get("page_span")
    page_num = row.get("page_num")
    if page_span not in (None, ""):
        return str(page_span)
    if page_num not in (None, ""):
        return str(page_num)
    return ""


def has_page_info(row: dict) -> bool:
    return get_page_display(row) != ""


def entity_specificity_score(entity_name: str, entity_type: str, question: str) -> int:
    """
    实体具体性打分：
    分数越高，越应该优先匹配
    """
    score = 0
    q = question or ""

    # 1. 长词优先
    score += len(entity_name) * 3

    # 2. 如果实体完整出现在原问题里，强加分
    if entity_name and entity_name in q:
        score += 30

    # 3. 设备/部件/故障类优先于过泛参数词
    if entity_type in {"Device", "Component", "Fault", "MaintenanceAction", "Cause", "Symptom"}:
        score += 15

    # 4. 典型专有设备名加分
    specific_hints = [
        "互感器", "变压器", "齿轮箱", "发电机组", "发电机", "风机",
        "断路器", "避雷器", "绝缘子", "轴承", "叶片", "塔架", "机舱"
    ]
    if any(h in entity_name for h in specific_hints):
        score += 20

    # 5. 泛词降权
    if entity_name in GENERIC_ENTITY_TERMS:
        score -= 25

    # 6. 如果实体只是问题的一小部分，且特别短，再降一点
    if len(entity_name) <= 2:
        score -= 8

    return score


def build_entity_candidates_from_question(question: str):
    """
    从原问题中找所有可能匹配到的实体候选
    """
    q = normalize_text(question)
    candidates = []

    for row in get_all_entities():
        name = row["name"]
        etype = row["type"]

        if not name:
            continue

        # 完全包含 / 反向包含
        if name in q or q in name:
            score = entity_specificity_score(name, etype, q)
            candidates.append({
                "name": name,
                "type": etype,
                "_score": score
            })

    candidates = sorted(
        candidates,
        key=lambda x: (x["_score"], len(x["name"])),
        reverse=True
    )
    return candidates


def load_jsonl(file_path: Path):
    rows = []
    if not file_path.exists():
        logger.warning("数据文件不存在：%s", file_path)
        return rows
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        logger.exception("读取 JSONL 文件失败：%s", file_path)
        return []
    return rows


_RELATION_ROWS_CACHE: list[dict] | None = None
_RELATION_ROWS_LOAD_FAILED = False


def get_relation_rows() -> list[dict]:
    """
    懒加载关系 JSONL，进程内缓存复用。
    读取失败不抛异常，返回空列表，并做一次性轻量提示。
    """
    global _RELATION_ROWS_CACHE, _RELATION_ROWS_LOAD_FAILED

    if _RELATION_ROWS_CACHE is not None:
        return _RELATION_ROWS_CACHE

    try:
        _RELATION_ROWS_CACHE = load_jsonl(RELATIONS_FILE)
    except Exception:
        _RELATION_ROWS_CACHE = []
        if not _RELATION_ROWS_LOAD_FAILED:
            _RELATION_ROWS_LOAD_FAILED = True
            logger.exception("关系文件读取失败：%s", RELATIONS_FILE)

    return _RELATION_ROWS_CACHE


def get_all_entity_names():
    query = """
    MATCH (n:Entity)
    RETURN n.name AS name, n.type AS type
    """
    return run_query(query)


_ALL_ENTITIES_CACHE: list[dict] | None = None
_ALL_ENTITIES_LOAD_FAILED = False


def get_all_entities() -> list[dict]:
    """
    懒加载实体列表（Neo4j 查询），进程内缓存复用。
    查询失败不抛异常，返回空列表，并做一次性轻量提示。
    """
    global _ALL_ENTITIES_CACHE, _ALL_ENTITIES_LOAD_FAILED

    if _ALL_ENTITIES_CACHE is not None:
        return _ALL_ENTITIES_CACHE

    try:
        _ALL_ENTITIES_CACHE = get_all_entity_names()
    except Exception:
        _ALL_ENTITIES_CACHE = []
        if not _ALL_ENTITIES_LOAD_FAILED:
            _ALL_ENTITIES_LOAD_FAILED = True
            logger.exception("Neo4j 实体列表加载失败")

    return _ALL_ENTITIES_CACHE


def detect_intent(question: str) -> str:
    q = question.strip()

    # 优先级很重要，先识别更具体的问题
    ordered_intents = [
        "部件故障",
        "故障症状",
        "故障原因",
        "处理措施",
        "检测方法",
        "参数要求",
        "使用方法",
        "条件约束",
        "措施要求",
        "作用用途",
        "定义说明"
    ]

    for intent in ordered_intents:
        hints = QUESTION_HINTS.get(intent, [])
        if any(h in q for h in hints):
            return intent
    return "综合查询"


def extract_entity_from_question(question: str) -> str:
    q = normalize_text(question)

    for hints in QUESTION_HINTS.values():
        for h in hints:
            q = q.replace(h, "")

    q = q.replace("有哪些", "").replace("有什么", "")
    q = q.replace("可能", "").replace("相关", "")
    q = q.replace("应", "").replace("通过", "")
    q = q.replace("的", "")
    q = q.strip("？? ：:，,。 ")

    return q


def fuzzy_match_entity(entity_guess: str, original_question: str = ""):
    """
    精修版实体匹配逻辑：
    1. 完全匹配优先
    2. 基于原问题做候选搜索
    3. 最长、更具体实体优先
    4. 泛词降权
    """
    if not entity_guess and not original_question:
        return None

    q_guess = normalize_text(entity_guess)
    q_full = normalize_text(original_question)

    # ===== 1. 完全匹配优先 =====
    for row in get_all_entities():
        if row["name"] == q_guess:
            return row

    # ===== 2. 先基于“原问题”做候选 =====
    full_candidates = build_entity_candidates_from_question(q_full)
    if full_candidates:
        return {
            "name": full_candidates[0]["name"],
            "type": full_candidates[0]["type"]
        }

    # ===== 3. 再基于“抽取后的实体猜测”做候选 =====
    guess_candidates = []
    for row in get_all_entities():
        name = row["name"]
        etype = row["type"]

        if not name:
            continue

        if q_guess in name or name in q_guess:
            score = entity_specificity_score(name, etype, q_full or q_guess)
            guess_candidates.append({
                "name": name,
                "type": etype,
                "_score": score
            })

    guess_candidates = sorted(
        guess_candidates,
        key=lambda x: (x["_score"], len(x["name"])),
        reverse=True
    )

    if guess_candidates:
        return {
            "name": guess_candidates[0]["name"],
            "type": guess_candidates[0]["type"]
        }

    return None


def retrieve_graph_neighbors(entity_name: str, limit=50):
    query = """
    MATCH (n:Entity {name: $entity_name})-[r]->(m:Entity)
    RETURN
        n.name AS source_name,
        n.type AS source_type,
        type(r) AS relation_en,
        coalesce(r.rel_zh, type(r)) AS relation_zh,
        m.name AS target_name,
        m.type AS target_type,
        r.file_name AS file_name,
        r.page_num AS page_num,
        r.page_span AS page_span,
        r.chunk_id AS chunk_id,
        r.source_sentence AS source_sentence
    LIMIT $limit
    """
    return run_query(query, {"entity_name": entity_name, "limit": limit})


def retrieve_reverse_faults(component_name: str, limit=50):
    query = """
    MATCH (f:Entity)-[r:OCCURS_ON]->(c:Entity {name: $entity_name})
    RETURN
        c.name AS source_name,
        c.type AS source_type,
        type(r) AS relation_en,
        coalesce(r.rel_zh, type(r)) AS relation_zh,
        f.name AS target_name,
        f.type AS target_type,
        r.file_name AS file_name,
        r.page_num AS page_num,
        r.page_span AS page_span,
        r.chunk_id AS chunk_id,
        r.source_sentence AS source_sentence
    LIMIT $limit
    """
    return run_query(query, {"entity_name": component_name, "limit": limit})


def contains_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def score_graph_row(row: dict, question: str, intent: str) -> int:
    score = 0
    text = normalize_text(row.get("source_sentence", ""))
    rel_en = row.get("relation_en", "")
    target = row.get("target_name", "")
    target_type = row.get("target_type", "")
    file_name = row.get("file_name", "") or ""

    if target and target in text:
        score += 3

    if has_page_info(row):
        score += 1

    if any(x in file_name for x in ["标准", "规范", "规程", "监督", "技术"]):
        score += 1

    # 按关系精准加分
    preferred_rels = INTENT_RELATION_FILTER.get(intent, set())
    if rel_en in preferred_rels:
        score += 5

    # 按目标类型加分
    preferred_types = INTENT_TARGET_TYPE_FILTER.get(intent, set())
    if target_type in preferred_types:
        score += 4

    # 按证据句内容加分
    if intent == "参数要求" and contains_any(text, ["应满足", "应符合", "限值", "误差", "不超过", "不低于"]):
        score += 3
    elif intent == "使用方法" and contains_any(text, ["试验", "检测", "测量", "校验", "监测"]):
        score += 3
    elif intent == "条件约束" and contains_any(text, ["环境温度", "海拔", "湿度", "户内", "户外", "条件"]):
        score += 3
    elif intent in ["措施要求", "处理措施"] and contains_any(text, ["更换", "检修", "停运", "维修", "处理", "加强监测"]):
        score += 3
    elif intent == "故障症状" and contains_any(text, ["症状", "表现", "伴有", "异响", "升高", "振动增大", "告警"]):
        score += 3
    elif intent == "故障原因" and contains_any(text, ["由于", "导致", "引起", "原因", "造成"]):
        score += 3
    elif intent == "检测方法" and contains_any(text, ["检测", "监测", "试验", "测量", "校验", "巡视", "巡检"]):
        score += 3
    elif intent in ["作用用途", "定义说明"]:
        score += 1

    # 问题关键词命中
    q_keywords = re.findall(r'[\u4e00-\u9fffA-Za-z0-9]+', question)
    for kw in q_keywords:
        if len(kw) >= 2 and kw in text:
            score += 1

    return score


def deduplicate_rows(rows):
    seen = set()
    result = []
    for r in rows:
        key = (
            r.get("source_name", ""),
            r.get("relation_en", ""),
            r.get("target_name", "")
        )
        if key not in seen:
            result.append(r)
            seen.add(key)
    return result


def filter_rows_by_intent(rows: list, intent: str) -> list:
    if not rows:
        return rows

    # 作用/定义/综合查询不过滤太死
    if intent in ["作用用途", "定义说明", "综合查询"]:
        # 但按优先级排序
        rel_priority = {rel: i for i, rel in enumerate(GENERAL_INTENT_PRIORITY)}
        return sorted(
            rows,
            key=lambda x: rel_priority.get(x.get("relation_en", ""), 999)
        )

    preferred_rels = INTENT_RELATION_FILTER.get(intent, set())
    preferred_types = INTENT_TARGET_TYPE_FILTER.get(intent, set())

    filtered = []
    for r in rows:
        rel_ok = (not preferred_rels) or (r.get("relation_en") in preferred_rels)
        type_ok = (not preferred_types) or (r.get("target_type") in preferred_types)

        if rel_ok or type_ok:
            filtered.append(r)

    # 如果过严导致没数据，就回退原结果
    return filtered if filtered else rows


def retrieve_text_evidence(entity_name: str, top_targets: list[str], limit=8):
    evidence = []
    for row in get_relation_rows():
        sent = normalize_text(row.get("source_sentence", ""))
        if not sent:
            continue

        if entity_name in sent:
            hit = False
            for t in top_targets:
                if t and t in sent:
                    hit = True
                    break

            if hit:
                page_display = (
                    str(row.get("page_span"))
                    if row.get("page_span") not in (None, "")
                    else str(row.get("page_num"))
                    if row.get("page_num") not in (None, "")
                    else ""
                )
                evidence.append({
                    "file_name": row.get("file_name", ""),
                    "page_num": row.get("page_num", ""),
                    "page_span": row.get("page_span", ""),
                    "page_display": page_display,
                    "source_sentence": sent,
                    "relation": row.get("relation", ""),
                    "chunk_id": row.get("chunk_id", "")
                })

    seen = set()
    result = []
    for e in evidence:
        key = (e["file_name"], e.get("page_display", ""), e["source_sentence"])
        if key not in seen:
            result.append(e)
            seen.add(key)

    return result[:limit]


def collect_top_targets(graph_rows: list, limit=5):
    items = []
    seen = set()
    for r in graph_rows:
        target = r.get("target_name", "")
        if target and target not in seen:
            items.append(target)
            seen.add(target)
        if len(items) >= limit:
            break
    return items


def make_relation_summary_phrase(graph_rows: list):
    rel_groups = defaultdict(list)
    for r in graph_rows:
        rel_zh = r.get("relation_zh", r.get("relation_en", "相关"))
        target = r.get("target_name", "")
        if target:
            rel_groups[rel_zh].append(target)

    pieces = []
    for rel, values in rel_groups.items():
        uniq_vals = []
        seen = set()
        for v in values:
            if v not in seen:
                uniq_vals.append(v)
                seen.add(v)
        pieces.append(f"{rel}包括：{'、'.join(uniq_vals[:4])}")

    return "；".join(pieces[:4])


def build_answer_confidence(intent: str, graph_rows: list, evidence_rows: list) -> dict:
    graph_hit_count = len(graph_rows or [])
    evidence_count = len(evidence_rows or [])
    source_files = {e.get("file_name", "") for e in (evidence_rows or []) if e.get("file_name", "")}
    source_count = len(source_files)
    has_page_refs = any(
        str(e.get("page_display", "") or e.get("page_span", "") or e.get("page_num", "")).strip()
        for e in (evidence_rows or [])
    )

    score = 0
    score += min(graph_hit_count, 8) * 5
    score += min(evidence_count, 8) * 5
    if source_count >= 2:
        score += 10
    if has_page_refs:
        score += 10

    if intent in INTENT_RELATION_FILTER and graph_rows:
        preferred = INTENT_RELATION_FILTER.get(intent, set())
        if any(r.get("relation_en", "") in preferred for r in graph_rows):
            score += 10

    score = max(0, min(score, 100))

    if score >= 75:
        level = "高"
        reason = "图谱与文本证据较充分，来源信息较完整。"
    elif score >= 45:
        level = "中"
        reason = "已有一定证据支撑，建议结合原文条款进一步核验。"
    else:
        level = "低"
        reason = "证据条数或来源信息不足，结论需谨慎参考。"

    return {
        "level": level,
        "score": score,
        "graph_hit_count": graph_hit_count,
        "evidence_count": evidence_count,
        "source_count": source_count,
        "has_page_refs": has_page_refs,
        "reason": reason
    }


def generate_template_answer(question: str, entity_name: str, intent: str, graph_rows: list, evidence_rows: list):
    if not graph_rows:
        return f"未在图谱中检索到与“{entity_name}”直接相关的知识。"

    top_targets = collect_top_targets(graph_rows, limit=5)
    joined = "、".join(top_targets)

    # 作用/定义类：改为解释型回答
    if intent == "作用用途":
        relation_summary = make_relation_summary_phrase(graph_rows[:6])
        answer = (
            f"根据知识图谱及相关标准文本，{entity_name}主要与{joined}等内容相关，"
            f"说明其在运行监测、状态评估、参数控制或技术监督中具有一定作用。"
        )
        if relation_summary:
            answer += f" 从现有证据看，其关联知识主要体现为：{relation_summary}。"

    elif intent == "定义说明":
        relation_summary = make_relation_summary_phrase(graph_rows[:6])
        if not joined or len(joined.strip()) < 3:
            concept_phrase = "参数要求、试验方法和运行条件"
        else:
            concept_phrase = f"{joined}等知识项"
        answer = f"在当前图谱证据范围内，可将“{entity_name}”理解为与{concept_phrase}密切相关的关键对象。"
        if relation_summary:
            answer += f" 从已检索到的关联关系看，主要包括：{relation_summary}。"
        else:
            answer += " 从已检索到的关联信息看，其内容主要体现在参数、方法、条件或措施等方面。"
        answer += " 目前尚未定位到标准文本中可直接引用的通用定义条款，因此以上为基于现有证据的概括性说明。"

    elif intent == "部件故障":
        answer = f"根据图谱与文本证据，{entity_name}相关的主要故障包括：{joined}。"

    elif intent == "故障症状":
        answer = f"根据图谱与文本证据，{entity_name}相关的主要症状包括：{joined}。"

    elif intent == "故障原因":
        answer = f"根据图谱与文本证据，{entity_name}可能的主要原因包括：{joined}。"

    elif intent == "处理措施":
        action_rows = [
            r for r in graph_rows
            if r.get("relation_en", "") in {"RESOLVED_BY", "REQUIRES_ACTION"}
            or r.get("target_type", "") in {"Action", "MaintenanceAction"}
        ]
        action_targets = collect_top_targets(action_rows, limit=5)
        if action_targets:
            action_joined = "、".join(action_targets)
            answer = f"根据图谱与文本证据，针对{entity_name}可采取的主要处理措施包括：{action_joined}。"
        else:
            answer = (
                f"当前未检索到与“{entity_name}”直接对应的明确处理措施条款。"
                "现有结果主要反映相关现象、部件或参数信息，不能直接等同于处理措施。"
            )

    elif intent == "检测方法":
        answer = f"根据图谱与文本证据，{entity_name}相关的主要检测方法包括：{joined}。"

    elif intent == "参数要求":
        answer = f"根据图谱与文本证据，{entity_name}相关的主要参数要求包括：{joined}。"

    elif intent == "使用方法":
        answer = f"根据图谱与文本证据，{entity_name}相关的主要使用方法包括：{joined}。"

    elif intent == "条件约束":
        answer = f"根据图谱与文本证据，{entity_name}相关的主要条件约束包括：{joined}。"

    elif intent == "措施要求":
        answer = f"根据图谱与文本证据，{entity_name}相关的主要措施要求包括：{joined}。"

    else:
        relation_summary = make_relation_summary_phrase(graph_rows[:6])
        answer = f"根据图谱与文本证据，{entity_name}的相关知识主要包括：{joined}。"
        if relation_summary:
            answer += f" 进一步看，其关联内容主要体现为：{relation_summary}。"

    if evidence_rows:
        first_evidence = evidence_rows[0]
        file_name = first_evidence.get("file_name", "")
        page_display = (
            first_evidence.get("page_display", "")
            or first_evidence.get("page_span", "")
            or first_evidence.get("page_num", "")
        )
        if file_name:
            answer += f" 相关依据可参考《{file_name}》"
            if str(page_display).strip():
                answer += f"第 {page_display} 页"
            answer += "的相关条文。"

    return answer


def generate_rag_answer_enhanced(question: str, entity_name: str, intent: str, graph_rows: list, evidence_rows: list):
    timeout = getattr(config, "LLM_TIMEOUT", 15)
    llm_answer = generate_answer_with_llm(
        question=question,
        entity_name=entity_name,
        intent=intent,
        graph_rows=graph_rows,
        evidence_rows=evidence_rows,
        timeout=timeout
    )

    if llm_answer and len(llm_answer.strip()) >= 15:
        return llm_answer.strip()

    return generate_template_answer(question, entity_name, intent, graph_rows, evidence_rows)


def generate_rag_answer(question: str, entity_name: str, intent: str, graph_rows: list, evidence_rows: list):
    return generate_rag_answer_enhanced(question, entity_name, intent, graph_rows, evidence_rows)


def graph_rag_answer(question: str):
    try:
        question = normalize_text(question)
        if not question:
            return {
                "question": question,
                "entity_name": "",
                "intent": "",
                "answer": "问题为空。",
                "graph_results": [],
                "evidence_results": [],
                "confidence_info": {
                    "level": "低",
                    "score": 0,
                    "graph_hit_count": 0,
                    "evidence_count": 0,
                    "source_count": 0,
                    "has_page_refs": False,
                    "reason": "问题为空，暂无可评估证据。"
                }
            }

        intent = detect_intent(question)
        entity_guess = extract_entity_from_question(question)
        entity_match = fuzzy_match_entity(entity_guess, original_question=question)

        if not entity_match:
            return {
                "question": question,
                "entity_name": entity_guess,
                "intent": intent,
                "answer": f"未在图谱实体中识别到与“{entity_guess}”匹配的实体。",
                "graph_results": [],
                "evidence_results": [],
                "confidence_info": {
                    "level": "低",
                    "score": 0,
                    "graph_hit_count": 0,
                    "evidence_count": 0,
                    "source_count": 0,
                    "has_page_refs": False,
                    "reason": "未识别到匹配实体，暂无有效检索证据。"
                }
            }

        entity_name = entity_match["name"]

        # 根据意图选择图谱查询策略
        if intent == "部件故障":
            graph_rows = retrieve_reverse_faults(entity_name, limit=80)
        else:
            graph_rows = retrieve_graph_neighbors(entity_name, limit=120)

        # 先做意图过滤
        graph_rows = filter_rows_by_intent(graph_rows, intent)

        # 再打分
        for row in graph_rows:
            row["_score"] = score_graph_row(row, question, intent)
            row["page_display"] = get_page_display(row)

        graph_rows = sorted(graph_rows, key=lambda x: x.get("_score", 0), reverse=True)
        graph_rows = deduplicate_rows(graph_rows)[:8]

        top_targets = collect_top_targets(graph_rows, limit=5)
        evidence_rows = retrieve_text_evidence(entity_name, top_targets, limit=8)
        answer = generate_rag_answer(question, entity_name, intent, graph_rows, evidence_rows)
        confidence_info = build_answer_confidence(intent, graph_rows, evidence_rows)

        if not getattr(config, "LLM_ENABLED", False):
            confidence_info["note"] = "当前未启用大模型回答，已切换到模板回答。"

        if not get_relation_rows():
            confidence_info["data_warning"] = "未找到关系数据文件，请先执行抽取和建图流程。"

        return {
            "question": question,
            "entity_name": entity_name,
            "intent": intent,
            "answer": answer,
            "graph_results": graph_rows,
            "evidence_results": evidence_rows,
            "confidence_info": confidence_info
        }
    except Exception:
        logger.exception("graph_rag_answer 执行异常。question=%s", question)
        return {
            "question": question,
            "entity_name": "",
            "intent": "",
            "answer": "GraphRAG 查询失败，请检查 Neo4j 连接、关系文件和配置。",
            "graph_results": [],
            "evidence_results": [],
            "confidence_info": {
                "level": "低",
                "score": 0,
                "graph_hit_count": 0,
                "evidence_count": 0,
                "source_count": 0,
                "has_page_refs": False,
                "reason": "系统异常，未能完成检索与生成。"
            }
        }