from pathlib import Path
import json
import re
from tqdm import tqdm

# ========= 1. 路径配置 =========
INPUT_DIR = Path(r"E:\WORK\data\chunks")
OUTPUT_DIR = Path(r"E:\WORK\data\meta")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ENTITIES_FILE = OUTPUT_DIR / "entities_v3.jsonl"
RELATIONS_FILE = OUTPUT_DIR / "relations_v3.jsonl"

# ========= 2. 原有词表（简化保留） =========
DEVICE_TERMS = [
    "风力发电机组", "风机", "齿轮箱", "叶片", "塔架", "机舱", "发电机",
    "变压器", "互感器", "电压互感器", "电流互感器", "断路器", "避雷器", "绝缘子"
]

PARAMETER_TERMS = [
    "温度", "湿度", "压力", "电压", "电流", "频率", "绝缘电阻", "温升", "误差", "振动"
]

METHOD_TERMS = [
    "耐压试验", "局部放电检测", "红外测温", "绝缘试验", "带电检测", "巡检",
    "校验", "测量", "验收试验", "预防性试验", "在线监测", "巡视检查"
]

CONDITION_TERMS = [
    "正常环境条件", "特殊使用条件", "海拔", "环境温度", "相对湿度",
    "户内", "户外", "运行条件", "使用条件"
]

ACTION_TERMS = [
    "采取措施", "定期检查", "加强监测", "停止运行", "更换", "维修", "检修",
    "整改", "停运", "维护", "复测"
]

# ========= 3. 新增风机运维词表 =========
COMPONENT_TERMS = [
    "风力发电机组", "风机", "叶片", "轮毂", "主轴", "主轴承", "齿轮箱", "发电机",
    "塔架", "机舱", "偏航系统", "变桨系统", "制动系统", "联轴器", "轴承",
    "冷却系统", "润滑系统", "液压系统", "变流器", "控制柜", "传感器",
    "电缆", "滑环", "变压器", "互感器", "断路器", "避雷器", "绝缘子"
]

FAULT_TERMS = [
    "过热", "振动超限", "异常振动", "漏油", "裂纹", "腐蚀", "绝缘老化",
    "局部放电", "放电异常", "跳闸", "误动作", "停机故障", "短路", "接地故障",
    "磨损", "松动", "卡涩", "失效", "烧损", "击穿", "断裂", "变形",
    "渗漏", "温升异常", "过压", "过流", "故障"
]

SYMPTOM_TERMS = [
    "温度升高", "异响", "噪声增大", "振动增大", "油位下降", "电流异常",
    "电压异常", "功率波动", "告警信号", "绝缘下降", "发热", "冒烟",
    "放电声", "渗油", "温升过高", "运行异常", "信号异常", "频繁告警",
    "跳闸现象", "异常停机"
]

CAUSE_TERMS = [
    "润滑不足", "受潮", "老化", "安装不当", "过载运行", "接触不良", "密封失效",
    "环境温度过高", "疲劳损伤", "污染", "腐蚀", "参数设置不当", "绝缘受损",
    "冷却不良", "紧固不足", "电气老化", "振动疲劳", "设计缺陷", "维护不当",
    "电压波动", "过电压", "短路冲击"
]

MAINTENANCE_ACTION_TERMS = [
    "更换", "检修", "润滑", "紧固", "清洗", "校验", "停运", "复测",
    "巡检", "加强监测", "维修", "调整参数", "更换部件", "停机检查",
    "及时处理", "消缺", "修复", "更换轴承", "更换油封", "补充润滑",
    "重新紧固", "加强巡视"
]

STANDARD_PATTERNS = [
    r"(DL/T\s*\d+(?:\.\d+)?\s*-\s*\d{4})",
    r"(GB/T\s*\d+(?:\.\d+)?\s*-\s*\d{4})",
    r"(NB/T\s*\d+(?:\.\d+)?\s*-\s*\d{4})",
    r"(Q/HN\s*[-－]?\s*\d+(?:\.\d+)?(?:[-－]\d+)?)"
]

# ========= 4. 工具函数 =========
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

# ========= 5. 实体抽取 =========
def extract_entities_from_text(text: str):
    text = normalize_text(text)

    entities = []
    entities.extend(find_standard_entities(text))
    entities.extend(find_term_entities(text, DEVICE_TERMS, "Device"))
    entities.extend(find_term_entities(text, PARAMETER_TERMS, "Parameter"))
    entities.extend(find_term_entities(text, METHOD_TERMS, "Method"))
    entities.extend(find_term_entities(text, CONDITION_TERMS, "Condition"))
    entities.extend(find_term_entities(text, ACTION_TERMS, "Action"))

    # 新增
    entities.extend(find_term_entities(text, COMPONENT_TERMS, "Component"))
    entities.extend(find_term_entities(text, FAULT_TERMS, "Fault"))
    entities.extend(find_term_entities(text, SYMPTOM_TERMS, "Symptom"))
    entities.extend(find_term_entities(text, CAUSE_TERMS, "Cause"))
    entities.extend(find_term_entities(text, MAINTENANCE_ACTION_TERMS, "MaintenanceAction"))

    return unique_entities(entities)

# ========= 6. 关系抽取 =========
def extract_relations_from_sentence(sentence, entities):
    relations = []
    seen = set()

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

    # ===== 保留原有部分核心关系 =====
    if any(x in sentence for x in ["应满足", "应符合", "不超过", "不低于", "限值", "误差"]) and devices and params:
        for d in devices:
            for p in params:
                add_unique_relation(relations, seen, d, "HAS_PARAMETER", p)

    if methods and devices and any(x in sentence for x in ["试验", "检测", "测量", "校验"]):
        for d in devices:
            for m in methods:
                add_unique_relation(relations, seen, d, "USES_METHOD", m)

    if any(x in sentence for x in ["条件", "环境温度", "相对湿度", "海拔", "户内", "户外"]) and devices and conditions:
        for d in devices:
            for c in conditions:
                add_unique_relation(relations, seen, d, "UNDER_CONDITION", c)

    if any(x in sentence for x in ["应采取", "应进行", "加强监测", "更换", "维修", "检修", "停运", "整改"]) and devices and actions:
        for d in devices:
            for a in actions:
                add_unique_relation(relations, seen, d, "REQUIRES_ACTION", a)

    # ===== 新增风机运维关系 =====

    # 1. 故障发生于部件
    if components and faults:
        if any(x in sentence for x in ["发生", "出现", "存在", "故障", "异常"]):
            for f in faults:
                for c in components:
                    add_unique_relation(relations, seen, f, "OCCURS_ON", c)

    # 2. 故障具有症状
    if faults and symptoms:
        if any(x in sentence for x in ["表现为", "症状为", "伴随", "出现", "呈现"]):
            for f in faults:
                for s in symptoms:
                    add_unique_relation(relations, seen, f, "HAS_SYMPTOM", s)

    # 3. 故障由原因引起
    if faults and causes:
        if any(x in sentence for x in ["由于", "因", "引起", "导致", "造成"]):
            for f in faults:
                for c in causes:
                    add_unique_relation(relations, seen, f, "CAUSED_BY", c)

    # 4. 故障通过维护措施处理
    if faults and maintenance_actions:
        if any(x in sentence for x in ["应", "应及时", "建议", "需要", "采取", "处理", "维修", "更换", "检修"]):
            for f in faults:
                for a in maintenance_actions:
                    add_unique_relation(relations, seen, f, "RESOLVED_BY", a)

    # 5. 故障/部件通过方法检测
    if methods and (faults or components):
        if any(x in sentence for x in ["检测", "试验", "测量", "监测", "校验"]):
            for f in faults:
                for m in methods:
                    add_unique_relation(relations, seen, f, "DETECTED_BY", m)
            for c in components:
                for m in methods:
                    add_unique_relation(relations, seen, c, "DETECTED_BY", m)

    return relations

# ========= 7. 主流程 =========
chunk_files = list(INPUT_DIR.rglob("*.jsonl"))

entity_records = []
relation_records = []

entity_seen_global = set()
relation_seen_global = set()

for file_path in tqdm(chunk_files, desc="抽取实体关系-v3"):
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

# ========= 8. 写出结果 =========
with open(ENTITIES_FILE, "w", encoding="utf-8") as f:
    for item in entity_records:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

with open(RELATIONS_FILE, "w", encoding="utf-8") as f:
    for item in relation_records:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

# ========= 9. 统计 =========
entity_type_count = {}
for e in entity_records:
    entity_type_count[e["entity_type"]] = entity_type_count.get(e["entity_type"], 0) + 1

relation_type_count = {}
for r in relation_records:
    relation_type_count[r["relation"]] = relation_type_count.get(r["relation"], 0) + 1

print("\n实体关系抽取-v3完成。")
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