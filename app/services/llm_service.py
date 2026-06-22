import json
import logging
from urllib import error, request

import config

MIN_VALID_ANSWER_LEN = 15
logger = logging.getLogger(__name__)


def _safe_config(name: str, default: str = "") -> str:
    value = getattr(config, name, default)
    if value is None:
        return default
    return str(value).strip()


def _to_display_page(row: dict) -> str:
    page_span = row.get("page_span")
    page_num = row.get("page_num")
    if page_span not in (None, ""):
        return str(page_span)
    if page_num not in (None, ""):
        return str(page_num)
    return ""


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    return " ".join(str(text).replace("\r", " ").replace("\n", " ").split())


def _build_graph_context(graph_rows: list, max_rows: int = 8) -> str:
    if not graph_rows:
        return "无图谱结果。"

    lines = []
    for i, row in enumerate(graph_rows[:max_rows], start=1):
        source_name = row.get("source_name", "")
        relation_zh = row.get("relation_zh", "") or row.get("relation_en", "相关")
        target_name = row.get("target_name", "")
        target_type = row.get("target_type", "")
        source_sentence = _normalize_text(row.get("source_sentence", ""))
        file_name = row.get("file_name", "")
        page_display = _to_display_page(row)

        line = (
            f"{i}. {source_name} --[{relation_zh}]--> {target_name}"
            f"（目标类型：{target_type or '未知'}）"
        )
        if source_sentence:
            line += f"；证据句：{source_sentence}"
        if file_name:
            line += f"；来源：{file_name}"
            if page_display:
                line += f" 第{page_display}页"
        lines.append(line)

    return "\n".join(lines)


def _build_evidence_context(evidence_rows: list, max_rows: int = 8) -> str:
    if not evidence_rows:
        return "无文本证据。"

    lines = []
    for i, row in enumerate(evidence_rows[:max_rows], start=1):
        sentence = _normalize_text(row.get("source_sentence", ""))
        file_name = row.get("file_name", "")
        page_display = row.get("page_display", "") or _to_display_page(row)

        line = f"{i}. {sentence or '（无证据句）'}"
        if file_name:
            line += f"；来源：{file_name}"
            if str(page_display).strip():
                line += f" 第{page_display}页"
        lines.append(line)

    return "\n".join(lines)


def build_graph_rag_messages(question, entity_name, intent, graph_rows, evidence_rows):
    graph_context = _build_graph_context(graph_rows, max_rows=8)
    evidence_context = _build_evidence_context(evidence_rows, max_rows=8)

    system_prompt = (
        "你是一个用于风机运维知识图谱问答的专业助手。\n"
        "请严格遵守以下要求：\n"
        "1) 只能依据用户提供的“图谱结果”和“文本证据”作答。\n"
        "2) 严禁编造任何未在证据中出现的事实、参数、结论或来源。\n"
        "3) 若证据不足，请明确说明“现有证据不足”，并给出已检索到的要点。\n"
        "4) 若图谱结果与文本证据存在不一致，应优先依据文本证据并谨慎表述。\n"
        "5) 若问题属于“定义说明/是什么”，且未检索到标准原文定义条款，"
        "应先给出基于图谱证据的概括性解释，再自然说明尚未定位到标准文本中的通用定义条款；"
        "不得将概括性解释表述为权威硬定义。\n"
        "6) 若问题属于“处理措施”，但图谱结果中未出现明确的措施类关系或措施类实体，"
        "必须明确说明“当前未检索到明确处理措施条款”，且不得将部件、现象、参数表述为处理措施。\n"
        "7) 回答风格需正式、自然、简洁，适合毕业设计系统演示。\n"
        "8) 优先给出结论，再用1-2句说明依据，可引用来源文件名与页码。"
    )

    user_prompt = (
        f"用户问题：{question}\n"
        f"识别实体：{entity_name}\n"
        f"识别意图：{intent}\n\n"
        f"【图谱结果】\n{graph_context}\n\n"
        f"【文本证据】\n{evidence_context}\n\n"
        "请基于以上信息生成最终回答。"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


def generate_answer_with_llm(
    question,
    entity_name,
    intent,
    graph_rows,
    evidence_rows,
    timeout=15
) -> str:
    llm_enabled_raw = _safe_config("LLM_ENABLED", "false").lower()
    llm_enabled = llm_enabled_raw in {"1", "true", "yes", "on"}
    if not llm_enabled:
        logger.info("LLM 未启用，跳过大模型调用。")
        return ""

    api_key = _safe_config("LLM_API_KEY")
    base_url = _safe_config("LLM_BASE_URL")
    model_name = _safe_config("LLM_MODEL_NAME")
    if timeout in (None, ""):
        try:
            timeout = int(_safe_config("LLM_TIMEOUT", "15"))
        except Exception:
            timeout = 15

    if not api_key or not base_url or not model_name:
        logger.warning("LLM 配置不完整，自动回退模板回答。")
        return ""

    # LLM_BASE_URL 仅配置到 /v1，这里在代码里拼接 /chat/completions。
    url = base_url.rstrip("/") + "/chat/completions"
    messages = build_graph_rag_messages(
        question=question,
        entity_name=entity_name,
        intent=intent,
        graph_rows=graph_rows or [],
        evidence_rows=evidence_rows or []
    )

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 600
    }

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except (error.HTTPError, error.URLError, TimeoutError, ValueError):
        logger.exception("LLM 请求失败，自动回退模板回答。")
        return ""
    except Exception:
        logger.exception("LLM 调用出现未知异常，自动回退模板回答。")
        return ""

    if not raw:
        logger.warning("LLM 响应为空，自动回退模板回答。")
        return ""

    try:
        data = json.loads(raw)
    except Exception:
        logger.exception("LLM 响应 JSON 解析失败，自动回退模板回答。")
        return ""

    choices = data.get("choices") or []
    if not choices:
        logger.warning("LLM 响应缺少 choices，自动回退模板回答。")
        return ""

    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        logger.warning("LLM 响应内容为空，自动回退模板回答。")
        return ""

    answer = str(content).strip()
    if not answer:
        logger.warning("LLM 回答为空白字符串，自动回退模板回答。")
        return ""
    if len(answer) < MIN_VALID_ANSWER_LEN:
        logger.warning("LLM 回答过短（len=%s），自动回退模板回答。", len(answer))
        return ""
    return answer
