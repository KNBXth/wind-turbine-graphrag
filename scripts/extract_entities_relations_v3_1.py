from pathlib import Path
import json
import re
from tqdm import tqdm
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import config

# ========= 1. 路径配置 =========
INPUT_DIR = config.CHUNKS_DIR
OUTPUT_DIR = config.META_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ENTITIES_FILE = OUTPUT_DIR / "entities_v3_1.jsonl"
RELATIONS_FILE = OUTPUT_DIR / "relations_v3_1.jsonl"

# ========= 2. 原有标准知识词表（保留精简版） =========
DEVICE_TERMS = [
    "风力发电机组", "风机", "齿轮箱", "叶片", "塔架", "机舱", "发电机",
    "变压器", "互感器", "电压互感器", "电流互感器", "断路器", "避雷器", "绝缘子"
]

PARAMETER_TERMS = [
    "温度", "湿度", "压力", "电压", "电流", "频率", "绝缘电阻", "温升", "误差", "振动",
    "露点", "油位", "功率", "噪声"
]

METHOD_TERMS = [
    "耐压试验", "局部放电检测", "红外测温", "绝缘试验", "带电检测", "巡检",
    "校验", "测量", "验收试验", "预防性试验", "在线监测", "巡视检查",
    "振动监测", "油液检测", "局放检测"
]

CONDITION_TERMS = [
    "正常环境条件", "特殊使用条件", "海拔", "环境温度", "相对湿度",
    "户内", "户外", "运行条件", "使用条件", "工况"
]

ACTION_TERMS = [
    "采取措施", "定期检查", "加强监测", "停止运行", "更换", "维修", "检修",
    "整改", "停运", "维护", "复测"
]

# ========= 3. 新增风机运维词表（v3.1 精修） =========
COMPONENT_TERMS = [
    "风力发电机组", "风机", "叶片", "轮毂", "主轴", "主轴承", "齿轮箱", "发电机",
    "塔架", "机舱", "偏航系统", "变桨系统", "制动系统", "联轴器", "轴承",
    "冷却系统", "润滑系统", "液压系统", "变流器", "控制柜", "传感器",
    "电缆", "滑环", "变压器", "互感器", "断路器", "避雷器", "绝缘子",
    "油封", "轴系", "机组", "变桨轴承", "偏航轴承"
]

# v3.1：去掉过泛 Fault 词，如“故障”“失效”“老化”“腐蚀”“变形”
FAULT_TERMS = [
    "过热", "振动超限", "异常振动", "漏油", "裂纹", "绝缘老化", "局部放电",
    "放电异常", "跳闸", "误动作", "停机故障", "短路", "接地故障", "磨损",
    "松动", "卡涩", "烧损", "击穿", "断裂", "渗漏", "温升异常", "过压",
    "过流", "绝缘下降", "异常停机", "油温异常", "振动异常", "绝缘击穿",
    "局放异常", "绝缘损坏", "轴承过热", "齿轮箱漏油", "叶片裂纹"
]

SYMPTOM_TERMS = [
    "温度升高", "异响", "噪声增大", "振动增大", "油位下降", "电流异常",
    "电压异常", "功率波动", "告警信号", "绝缘下降", "发热", "冒烟",
    "放电声", "渗油", "温升过高", "运行异常", "信号异常", "频繁告警",
    "跳闸现象", "异常停机", "异常声响", "油温升高", "振动过大",
    "温度异常", "电流波动", "电压波动", "绝缘电阻下降", "油压异常",
    "压力异常", "运行不稳", "启停频繁", "频繁停机", "输出异常",
    "效率下降", "噪声异常", "振动超标", "温升异常", "保护动作",
    "告警频发", "机组报警", "油温过高", "轴温升高", "壳体发热",
    "放电异响", "振动加剧", "转速波动"
]

SYMPTOM_TERMS = [
    "温度升高", "异响", "噪声增大", "振动增大", "油位下降", "电流异常",
    "电压异常", "功率波动", "告警信号", "绝缘下降", "发热", "冒烟",
    "放电声", "渗油", "温升过高", "运行异常", "信号异常", "频繁告警",
    "跳闸现象", "异常停机", "异常声响", "油温升高", "振动过大",
    "温度异常", "电流波动", "电压波动", "绝缘电阻下降", "油压异常",
    "压力异常", "运行不稳", "启停频繁", "频繁停机", "输出异常",
    "效率下降", "噪声异常", "振动超标", "温升异常", "保护动作",
    "告警频发", "机组报警", "油温过高", "轴温升高", "壳体发热",
    "放电异响", "振动加剧", "转速波动"
]

CAUSE_TERMS = [
    "润滑不足", "受潮", "安装不当", "过载运行", "接触不良", "密封失效",
    "环境温度过高", "疲劳损伤", "污染", "参数设置不当", "绝缘受损",
    "冷却不良", "紧固不足", "电气老化", "振动疲劳", "设计缺陷", "维护不当",
    "电压波动", "过电压", "短路冲击", "润滑不良", "散热不良", "长期运行",
    "油质劣化", "密封不严", "部件磨损", "受力不均",
    "高温环境", "低温环境", "潮湿环境", "盐雾腐蚀", "润滑油不足",
    "润滑油劣化", "安装偏差", "对中不良", "紧固件松动", "绝缘老化",
    "接地不良", "谐波影响", "瞬态过压", "疲劳裂纹", "长期振动",
    "冲击载荷", "冷却失效", "散热受阻", "油路堵塞", "滤芯堵塞",
    "润滑中断", "密封老化", "部件松脱", "参数漂移"
]

CAUSE_TERMS = [
    "润滑不足", "受潮", "安装不当", "过载运行", "接触不良", "密封失效",
    "环境温度过高", "疲劳损伤", "污染", "参数设置不当", "绝缘受损",
    "冷却不良", "紧固不足", "电气老化", "振动疲劳", "设计缺陷", "维护不当",
    "电压波动", "过电压", "短路冲击", "润滑不良", "散热不良", "长期运行",
    "油质劣化", "密封不严", "部件磨损", "受力不均"
]

MAINTENANCE_ACTION_TERMS = [
    "更换", "检修", "润滑", "紧固", "清洗", "校验", "停运", "复测",
    "巡检", "加强监测", "维修", "调整参数", "更换部件", "停机检查",
    "及时处理", "消缺", "修复", "更换轴承", "更换油封", "补充润滑",
    "重新紧固", "加强巡视", "停机检修", "更换润滑油"
]

STANDARD_PATTERNS = [
    r"(DL/T\s*\d+(?:\.\d+)?\s*-\s*\d{4})",
    r"(GB/T\s*\d+(?:\.\d+)?\s*-\s*\d{4})",
    r"(NB/T\s*\d+(?:\.\d+)?\s*-\s*\d{4})",
    r"(Q/HN\s*[-－]?\s*\d+(?:\.\d+)?(?:[-－]\d+)?)"
]

# ========= 4. 规则配置 =========
SKIP_PATTERNS = [
    "发布", "实施", "前言", "起草单位", "归口", "附录",
    "中国华能集团有限公司", "国家电网公司", "本标准由"
]

PARAMETER_TRIGGER_WORDS = ["应满足", "应符合", "不超过", "不低于", "限值", "误差", "应为", "宜为"]
METHOD_TRIGGER_WORDS = ["试验", "检测", "测量", "校验", "监测", "巡检", "巡视"]
CONDITION_TRIGGER_WORDS = ["条件", "环境温度", "相对湿度", "海拔", "户内", "户外", "运行条件", "使用条件"]
ACTION_TRIGGER_WORDS = ["应采取", "应进行", "加强监测", "更换", "维修", "检修", "停运", "整改"]

FAULT_ON_COMPONENT_TRIGGERS = ["发生", "出现", "存在", "异常", "故障", "过热", "漏油", "裂纹", "击穿", "跳闸"]
SYMPTOM_TRIGGERS = [
    "表现为", "症状为", "主要症状为", "伴有", "伴随", "可见", "出现", "呈现", "征兆为",
    "异常", "升高", "增大", "下降", "告警", "异响", "发热", "停机", "波动",
    "表征为", "现象为", "具体表现为", "典型表现为", "常见表现为", "可表现为", "多表现为",
    "症状包括", "表现包括", "征象为", "征象包括", "可观察到", "可监测到", "可检测到",
    "报警", "报警信号", "告警信号", "频繁告警", "告警频发", "保护动作", "跳闸现象",
    "运行不稳", "启停频繁", "输出波动", "温升过高", "油温升高", "振动过大", "噪声异常"
]

CAUSE_TRIGGERS = [
    "由于", "因", "引起", "导致", "造成", "原因为", "主要原因是", "多因", "引发",
    "易导致", "会造成", "可引起", "致使", "使得",
    "通常由", "一般由", "多由", "常由", "往往由", "多为", "主要由", "可由",
    "诱发", "诱因", "根因", "根本原因", "直接原因", "间接原因", "原因在于",
    "与", "有关", "相关", "密切相关", "受", "影响", "受...影响",
    "所致", "而致", "进而导致", "进一步导致", "从而导致", "最终导致", "继而引发",
    "在...情况下易", "在...条件下易", "在...工况下易", "当...时易", "当...时会",
    "是...原因", "是...诱因", "是造成...的原因"
]

RESOLVE_TRIGGERS = [
    "应", "应及时", "建议", "需要", "采取", "处理", "维修", "更换", "检修", "停运",
    "加强监测", "清洗", "润滑", "紧固", "校验", "修复", "复测", "巡视", "巡检"
]
DETECT_TRIGGERS = ["检测", "试验", "测量", "监测", "校验", "巡视", "巡检"]

# ========= 5. 工具函数 =========
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def split_sentences(text: str):
    text = normalize_text(text)
    if not text:
        return []
    parts = re.split(r'[。！？；;\n]+', text)
    return [p.strip() for p in parts if p.strip()]


def unique_entities(entities):
    result = []
    seen = set()
    for e in entities:
        key = (e["entity_name"], e["entity_type"])
        if key not in seen:
            result.append(e)
            seen.add(key)
    return result


def find_standard_entities(text: str):
    entities = []
    seen = set()
    for pattern in STANDARD_PATTERNS:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        for m in matches:
            name = re.sub(r"\s+", " ", m).strip()
            if name not in seen:
                entities.append({
                    "entity_name": name,
                    "entity_type": "Standard"
                })
                seen.add(name)
    return entities


def find_term_entities(text: str, term_list, entity_type):
    entities = []
    seen = set()
    sorted_terms = sorted(term_list, key=lambda x: len(x), reverse=True)
    for term in sorted_terms:
        if term in text and (term, entity_type) not in seen:
            entities.append({
                "entity_name": term,
                "entity_type": entity_type
            })
            seen.add((term, entity_type))
    return entities


def make_relation(head, relation, tail):
    return {
        "head_entity": head["entity_name"],
        "head_type": head["entity_type"],
        "relation": relation,
        "tail_entity": tail["entity_name"],
        "tail_type": tail["entity_type"]
    }


def add_unique_relation(relations, seen, head, relation, tail):
    key = (head["entity_name"], relation, tail["entity_name"])
    if key not in seen:
        relations.append(make_relation(head, relation, tail))
        seen.add(key)


def contains_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)

def sentence_len_ok_for_symptom(sent: str) -> bool:
    return len(sent) <= 80


def is_symptom_like_sentence(sent: str) -> bool:
    symptom_hints = [
        "异常", "升高", "增大", "下降", "告警", "异响", "发热",
        "停机", "波动", "渗油", "冒烟", "放电声", "运行异常"
    ]
    return contains_any(sent, symptom_hints)

def should_skip_chunk(text: str) -> bool:
    hit = sum(1 for p in SKIP_PATTERNS if p in text)
    return hit >= 3


# ========= 6. 实体抽取 =========
def extract_entities_from_text(text: str):
    text = normalize_text(text)

    entities = []
    entities.extend(find_standard_entities(text))

    # 原有
    entities.extend(find_term_entities(text, DEVICE_TERMS, "Device"))
    entities.extend(find_term_entities(text, PARAMETER_TERMS, "Parameter"))
    entities.extend(find_term_entities(text, METHOD_TERMS, "Method"))
    entities.extend(find_term_entities(text, CONDITION_TERMS, "Condition"))
    entities.extend(find_term_entities(text, ACTION_TERMS, "Action"))

    # v3.1 新增
    entities.extend(find_term_entities(text, COMPONENT_TERMS, "Component"))
    entities.extend(find_term_entities(text, FAULT_TERMS, "Fault"))
    entities.extend(find_term_entities(text, SYMPTOM_TERMS, "Symptom"))
    entities.extend(find_term_entities(text, CAUSE_TERMS, "Cause"))
    entities.extend(find_term_entities(text, MAINTENANCE_ACTION_TERMS, "MaintenanceAction"))

    return unique_entities(entities)


# ========= 7. 关系抽取 =========
def extract_relations_from_sentence(sentence, entities):
    relations = []
    seen = set()
    sent = normalize_text(sentence)

    devices = [e for e in entities if e["entity_type"] == "Device"]
    params = [e for e in entities if e["entity_type"] == "Parameter"]
    methods = [e for e in entities if e["entity_type"] == "Method"]
    conditions = [e for e in entities if e["entity_type"] == "Condition"]
    actions = [e for e in entities if e["entity_type"] == "Action"]

    components = [e for e in entities if e["entity_type"] == "Component"]
    faults = [e for e in entities if e["entity_type"] == "Fault"]
    symptoms = [e for e in entities if e["entity_type"] == "Symptom"]
    causes = [e for e in entities if e["entity_type"] == "Cause"]
    maintenance_actions = [e for e in entities if e["entity_type"] == "MaintenanceAction"]

    # ===== 原有标准知识关系（保留精简） =====
    if contains_any(sent, PARAMETER_TRIGGER_WORDS) and devices and params:
        for d in devices:
            for p in params:
                add_unique_relation(relations, seen, d, "HAS_PARAMETER", p)

    if contains_any(sent, METHOD_TRIGGER_WORDS) and devices and methods:
        for d in devices:
            for m in methods:
                add_unique_relation(relations, seen, d, "USES_METHOD", m)

    if contains_any(sent, CONDITION_TRIGGER_WORDS) and devices and conditions:
        for d in devices:
            for c in conditions:
                add_unique_relation(relations, seen, d, "UNDER_CONDITION", c)

    if contains_any(sent, ACTION_TRIGGER_WORDS) and devices and actions:
        for d in devices:
            for a in actions:
                add_unique_relation(relations, seen, d, "REQUIRES_ACTION", a)

    # ===== 新增运维故障关系：v3.1 精修 =====

    # 1. 故障发生于部件
    # 要求：Fault + Component，同时句中有故障/异常类触发词
    if faults and components and contains_any(sent, FAULT_ON_COMPONENT_TRIGGERS):
        for f in faults:
            for c in components:
                # 进一步约束：句子里最好同时出现两者
                if f["entity_name"] in sent and c["entity_name"] in sent:
                    add_unique_relation(relations, seen, f, "OCCURS_ON", c)

            # 2. 故障具有症状
    # v3.1 patch：强规则 + 弱规则 + 少量句式 regex 补召回
    if faults and symptoms:
        # 强/弱触发条件（原有）
        strong_or_weak_hit = False
        if contains_any(sent, SYMPTOM_TRIGGERS):
            strong_or_weak_hit = True
        elif sentence_len_ok_for_symptom(sent) and is_symptom_like_sentence(sent):
            strong_or_weak_hit = True

        for f in faults:
            for s in symptoms:
                if f["entity_name"] not in sent or s["entity_name"] not in sent:
                    continue

                f_esc = re.escape(f["entity_name"])
                s_esc = re.escape(s["entity_name"])

                # 句式补充：
                # 1) X 表现为 Y
                # 2) X 的症状包括 Y
                # 3) 出现 Y 现象（同句需有 X）
                symptom_regex_hit = (
                    re.search(rf"{f_esc}.{{0,12}}(?:表现为|症状为|症状包括|表现包括).{{0,12}}{s_esc}", sent)
                    or re.search(rf"{f_esc}的症状(?:包括|为).{{0,12}}{s_esc}", sent)
                    or re.search(rf"(?:出现|发生).{{0,8}}{s_esc}.{{0,4}}现象", sent)
                )
                if symptom_regex_hit:
                    print(
                        f"[DEBUG][HAS_SYMPTOM][regex_hit] fault={f['entity_name']} "
                        f"symptom={s['entity_name']} sent={sent}")

                if strong_or_weak_hit or symptom_regex_hit:
                    add_unique_relation(relations, seen, f, "HAS_SYMPTOM", s)

        # 3. 故障由原因引起
    # v3.1 patch：强规则 + 弱规则 + 少量句式 regex 补召回
    if faults and causes:
        weak_cause_hints = ["时", "会", "可", "易", "易于", "容易"]

        for f in faults:
            for c in causes:
                if f["entity_name"] not in sent or c["entity_name"] not in sent:
                    continue

                f_esc = re.escape(f["entity_name"])
                c_esc = re.escape(c["entity_name"])

                # 句式补充：
                # 1) X 由 Y 引起
                # 2) Y 是 X 的主要原因
                # 3) 由于 Y，发生 X
                cause_regex_hit = (
                    re.search(rf"{f_esc}.{{0,8}}由.{{0,12}}{c_esc}.{{0,8}}(?:引起|导致|造成)", sent)
                    or re.search(rf"{c_esc}.{{0,8}}是.{{0,6}}{f_esc}的(?:主要)?原因", sent)
                    or re.search(rf"由于.{{0,8}}{c_esc}.{{0,8}}(?:发生|出现|引发).{{0,10}}{f_esc}", sent)
                )
                if cause_regex_hit:
                    print(
                        f"[DEBUG][CAUSED_BY][regex_hit] fault={f['entity_name']} "
                        f"cause={c['entity_name']} sent={sent}")

                if contains_any(sent, CAUSE_TRIGGERS) or contains_any(sent, weak_cause_hints) or cause_regex_hit:
                    add_unique_relation(relations, seen, f, "CAUSED_BY", c)


    # 4. 故障通过维护措施处理
    # v3.1 patch：放宽措施关系
    if faults and maintenance_actions:
        if contains_any(sent, RESOLVE_TRIGGERS):
            for f in faults:
                for a in maintenance_actions:
                    if f["entity_name"] in sent and a["entity_name"] in sent:
                        add_unique_relation(relations, seen, f, "RESOLVED_BY", a)
        else:
            # 弱规则：若句中同时出现故障和措施动作，也允许抽
            for f in faults:
                for a in maintenance_actions:
                    if f["entity_name"] in sent and a["entity_name"] in sent:
                        add_unique_relation(relations, seen, f, "RESOLVED_BY", a)

    # 5. 故障/部件通过方法检测
    if methods and contains_any(sent, DETECT_TRIGGERS):
        for f in faults:
            for m in methods:
                if f["entity_name"] in sent and m["entity_name"] in sent:
                    add_unique_relation(relations, seen, f, "DETECTED_BY", m)
        for c in components:
            for m in methods:
                if c["entity_name"] in sent and m["entity_name"] in sent:
                    add_unique_relation(relations, seen, c, "DETECTED_BY", m)

    return relations


# ========= 8. 主流程 =========
chunk_files = list(INPUT_DIR.rglob("*.jsonl"))

entity_records = []
relation_records = []

entity_seen_global = set()
relation_seen_global = set()

for file_path in tqdm(chunk_files, desc="抽取实体关系-v3.1"):
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

            if should_skip_chunk(text):
                continue

            chunk_id = chunk.get("chunk_id", "")
            doc_id = chunk.get("doc_id", "")
            file_name = chunk.get("file_name", "")
            relative_path = chunk.get("relative_path", "")
            page_num = chunk.get("page_num")
            if page_num in (None, ""):
                page_start = chunk.get("page_start", "")
                page_end = chunk.get("page_end", "")
                if page_start != "" and page_end != "" and str(page_start) != str(page_end):
                    page_num = f"{page_start}-{page_end}"
                else:
                    page_num = page_start
            chunk_entities = extract_entities_from_text(text)

            for e in chunk_entities:
                entity_key = (
                    e["entity_name"],
                    e["entity_type"],
                    doc_id,
                    chunk_id
                )
                if entity_key not in entity_seen_global:
                    entity_records.append({
                        "entity_name": e["entity_name"],
                        "entity_type": e["entity_type"],
                        "doc_id": doc_id,
                        "file_name": file_name,
                        "relative_path": relative_path,
                        "page_num": page_num,
                        "chunk_id": chunk_id,
                        "source_text": text
                    })
                    entity_seen_global.add(entity_key)

            sentences = split_sentences(text)
            for sent in sentences:
                sent_entities = extract_entities_from_text(sent)
                if len(sent_entities) < 2:
                    continue

                sent_relations = extract_relations_from_sentence(sent, sent_entities)

                for r in sent_relations:
                    relation_key = (
                        r["head_entity"],
                        r["relation"],
                        r["tail_entity"],
                        doc_id,
                        chunk_id
                    )
                    if relation_key not in relation_seen_global:
                        relation_records.append({
                            "head_entity": r["head_entity"],
                            "head_type": r["head_type"],
                            "relation": r["relation"],
                            "tail_entity": r["tail_entity"],
                            "tail_type": r["tail_type"],
                            "doc_id": doc_id,
                            "file_name": file_name,
                            "relative_path": relative_path,
                            "page_num": page_num,
                            "chunk_id": chunk_id,
                            "source_sentence": sent
                        })
                        relation_seen_global.add(relation_key)

# ========= 9. 写出结果 =========
with open(ENTITIES_FILE, "w", encoding="utf-8") as f:
    for item in entity_records:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

with open(RELATIONS_FILE, "w", encoding="utf-8") as f:
    for item in relation_records:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

# ========= 10. 统计 =========
entity_type_count = {}
for e in entity_records:
    entity_type_count[e["entity_type"]] = entity_type_count.get(e["entity_type"], 0) + 1

relation_type_count = {}
for r in relation_records:
    relation_type_count[r["relation"]] = relation_type_count.get(r["relation"], 0) + 1

print("\n实体关系抽取-v3.1完成。")
print(f"实体总数: {len(entity_records)}")
print(f"关系总数: {len(relation_records)}")
print(f"实体输出文件: {ENTITIES_FILE}")
print(f"关系输出文件: {RELATIONS_FILE}")

print("\n实体类型统计:")
for k, v in sorted(entity_type_count.items(), key=lambda x: x[0]):
    print(f"  {k}: {v}")

print("\n关系类型统计:")
for k, v in sorted(relation_type_count.items(), key=lambda x: x[0]):
    print(f"  {k}: {v}")