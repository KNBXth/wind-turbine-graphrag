from pathlib import Path
import json
import re
from tqdm import tqdm

# ========= 1. 路径配置 =========
INPUT_DIR = Path(r"E:\WORK\data\chunks")
OUTPUT_DIR = Path(r"E:\WORK\data\meta")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ENTITIES_FILE = OUTPUT_DIR / "entities_v2.jsonl"
RELATIONS_FILE = OUTPUT_DIR / "relations_v2.jsonl"

# ========= 2. 领域词表（优化版） =========
DEVICE_TERMS = [
    "风力发电机组", "风机", "风电机组", "齿轮箱", "叶片", "塔架", "机舱", "发电机",
    "变压器", "互感器", "电压互感器", "电流互感器", "断路器", "继电器", "密度继电器",
    "开关柜", "接地装置", "绝缘子", "避雷器", "电缆", "母线", "GIS",
    "气体绝缘金属封闭开关设备", "采样测量装置", "监控系统", "自动化系统",
    "绝缘监督装置", "测量装置"
]

PARAMETER_TERMS = [
    "温度", "湿度", "压力", "电压", "电流", "频率", "局部放电", "绝缘电阻", "介质损耗",
    "相对湿度", "环境温度", "风速", "气压", "温升", "电压比", "误差", "含水量",
    "浓度", "露点", "振动", "噪声", "平均值", "限值", "上限", "下限"
]

# 方法词只保留“更明确的术语”，去掉过泛单词
METHOD_TERMS = [
    "耐压试验", "局部放电检测", "红外测温", "绝缘试验", "带电检测", "巡检",
    "校验", "测量", "验收试验", "交接试验", "预防性试验", "在线监测",
    "巡视检查", "红外检测", "局放检测", "绝缘电阻测量", "介质损耗测量"
]

CONDITION_TERMS = [
    "正常环境条件", "特殊使用条件", "海拔", "环境温度", "相对湿度", "户内", "户外",
    "污秽", "降水", "风速", "凝露", "海拔高度", "地震烈度", "运行条件",
    "正常条件", "使用条件"
]

ACTION_TERMS = [
    "采取措施", "定期检查", "加强监测", "停止运行", "更换", "维修", "检修",
    "校验", "验收", "记录", "处理", "整改", "停运", "巡视", "维护", "复测"
]

STANDARD_PATTERNS = [
    r"(DL/T\s*\d+(?:\.\d+)?\s*-\s*\d{4})",
    r"(GB/T\s*\d+(?:\.\d+)?\s*-\s*\d{4})",
    r"(NB/T\s*\d+(?:\.\d+)?\s*-\s*\d{4})",
    r"(Q/HN\s*[-－]?\s*\d+(?:\.\d+)?(?:[-－]\d+)?)"
]

# ========= 3. 工具函数 =========
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

    # 长词优先，避免短词覆盖长词
    sorted_terms = sorted(term_list, key=lambda x: len(x), reverse=True)

    for term in sorted_terms:
        if term in text and (term, entity_type) not in seen:
            entities.append({
                "entity_name": term,
                "entity_type": entity_type
            })
            seen.add((term, entity_type))

    return entities

def has_numeric_constraint(sentence: str) -> bool:
    patterns = [
        r"不超过", r"不应超过", r"不低于", r"不应低于",
        r"应为", r"宜为", r"应满足", r"应符合",
        r"平均值", r"限值", r"误差", r"上限", r"下限",
        r"\d+\s*(℃|°C|kPa|Pa|%|mm|m/s|V|A|Hz|mm²|kV)"
    ]
    return any(re.search(p, sentence) for p in patterns)

def has_apply_pattern(sentence: str) -> bool:
    patterns = [
        r"适用于",
        r"用于",
        r"适用范围",
        r"适用对象",
        r"本标准适用于",
        r"适用于下列"
    ]
    return any(re.search(p, sentence) for p in patterns)

def has_condition_pattern(sentence: str) -> bool:
    patterns = [
        r"条件下",
        r"环境温度",
        r"相对湿度",
        r"海拔",
        r"户内",
        r"户外",
        r"运行条件",
        r"正常环境条件",
        r"特殊使用条件"
    ]
    return any(re.search(p, sentence) for p in patterns)

def has_action_pattern(sentence: str) -> bool:
    patterns = [
        r"应采取",
        r"应进行",
        r"应定期",
        r"应记录",
        r"应检查",
        r"应校验",
        r"应维修",
        r"应更换",
        r"加强监测",
        r"采取措施",
        r"停止运行",
        r"停运",
        r"整改"
    ]
    return any(re.search(p, sentence) for p in patterns)

# ========= 4. 实体抽取 =========
def extract_entities_from_text(text: str):
    text = normalize_text(text)

    entities = []
    entities.extend(find_standard_entities(text))
    entities.extend(find_term_entities(text, DEVICE_TERMS, "Device"))
    entities.extend(find_term_entities(text, PARAMETER_TERMS, "Parameter"))
    entities.extend(find_term_entities(text, METHOD_TERMS, "Method"))
    entities.extend(find_term_entities(text, CONDITION_TERMS, "Condition"))
    entities.extend(find_term_entities(text, ACTION_TERMS, "Action"))

    return unique_entities(entities)

# ========= 5. 关系抽取 =========
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

def extract_relations_from_sentence(sentence, entities):
    relations = []
    seen = set()

    devices = [e for e in entities if e["entity_type"] == "Device"]
    params = [e for e in entities if e["entity_type"] == "Parameter"]
    methods = [e for e in entities if e["entity_type"] == "Method"]
    conditions = [e for e in entities if e["entity_type"] == "Condition"]
    actions = [e for e in entities if e["entity_type"] == "Action"]
    standards = [e for e in entities if e["entity_type"] == "Standard"]

    # 1. 标准适用于设备
    if has_apply_pattern(sentence) and standards and devices:
        for s in standards:
            for d in devices:
                add_unique_relation(relations, seen, s, "APPLIES_TO", d)

    # 2. 设备参数要求
    if has_numeric_constraint(sentence) and devices and params:
        for d in devices:
            for p in params:
                add_unique_relation(relations, seen, d, "HAS_PARAMETER", p)

    # 3. 设备使用方法
    # 只有出现明确方法名才连
    if methods and devices:
        for d in devices:
            for m in methods:
                add_unique_relation(relations, seen, d, "USES_METHOD", m)

    # 4. 设备处于条件下
    if has_condition_pattern(sentence) and devices and conditions:
        for d in devices:
            for c in conditions:
                add_unique_relation(relations, seen, d, "UNDER_CONDITION", c)

    # 5. 设备需要措施
    if has_action_pattern(sentence) and devices and actions:
        for d in devices:
            for a in actions:
                add_unique_relation(relations, seen, d, "REQUIRES_ACTION", a)

    return relations

# ========= 6. 主流程 =========
chunk_files = list(INPUT_DIR.rglob("*.jsonl"))

entity_records = []
relation_records = []

entity_seen_global = set()
relation_seen_global = set()

for file_path in tqdm(chunk_files, desc="抽取实体关系-v2"):
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

            chunk_id = chunk.get("chunk_id", "")
            doc_id = chunk.get("doc_id", "")
            file_name = chunk.get("file_name", "")
            relative_path = chunk.get("relative_path", "")
            page_num = chunk.get("page_num", "")

            # 过滤明显无业务价值的前言/发布类句段，可按需继续加
            skip_patterns = [
                "发布", "实施", "前言", "起草单位", "归口", "附录",
                "国家电网公司", "中国华能集团有限公司", "本标准由"
            ]
            if sum(1 for p in skip_patterns if p in text) >= 3:
                continue

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

# ========= 7. 写出结果 =========
with open(ENTITIES_FILE, "w", encoding="utf-8") as f:
    for item in entity_records:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

with open(RELATIONS_FILE, "w", encoding="utf-8") as f:
    for item in relation_records:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

# ========= 8. 统计 =========
entity_type_count = {}
for e in entity_records:
    entity_type_count[e["entity_type"]] = entity_type_count.get(e["entity_type"], 0) + 1

relation_type_count = {}
for r in relation_records:
    relation_type_count[r["relation"]] = relation_type_count.get(r["relation"], 0) + 1

print("\n实体关系抽取-v2完成。")
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