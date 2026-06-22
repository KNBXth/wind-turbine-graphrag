from pathlib import Path
import json
from neo4j import GraphDatabase
from tqdm import tqdm
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import config

# ========= 1. Neo4j 连接配置 =========
NEO4J_URI = config.NEO4J_URI
NEO4J_USER = config.NEO4J_USER
NEO4J_PASSWORD = config.NEO4J_PASSWORD

# ========= 2. 输入文件 =========
DATA_DIR = config.META_DIR
ENTITIES_FILE = config.ENTITIES_FILE
RELATIONS_FILE = config.RELATIONS_FILE

# ========= 3. 创建驱动 =========
driver = GraphDatabase.driver(
    NEO4J_URI,
    auth=(NEO4J_USER, NEO4J_PASSWORD)
)


# ========= 4. 读取 JSONL =========
def load_jsonl(file_path: Path):
    rows = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


# ========= 5. Neo4j 操作函数 =========
def create_constraints(tx):
    # 节点唯一约束：按 name + type
    tx.run("""
    CREATE CONSTRAINT entity_unique_name_type IF NOT EXISTS
    FOR (n:Entity)
    REQUIRE (n.name, n.type) IS UNIQUE
    """)


def clear_graph(tx):
    tx.run("MATCH (n) DETACH DELETE n")


def merge_entity(tx, entity_name, entity_type):
    tx.run("""
    MERGE (n:Entity {name: $name, type: $type})
    SET n.updated_at = datetime()
    """, name=entity_name, type=entity_type)


def merge_relation(tx, row):
    head_entity = row["head_entity"]
    head_type = row["head_type"]
    relation = row["relation"]
    tail_entity = row["tail_entity"]
    tail_type = row["tail_type"]

    doc_id = row.get("doc_id", "")
    file_name = row.get("file_name", "")
    relative_path = row.get("relative_path", "")
    page_span = row.get("page_span", "")   # <-- 改这里
    page_num = row.get("page_num", "")
    chunk_id = row.get("chunk_id", "")
    source_sentence = row.get("source_sentence", "")

    # 关系中文名映射
    relation_zh_map = {
        "HAS_PARAMETER": "参数要求",
        "USES_METHOD": "使用方法",
        "UNDER_CONDITION": "条件约束",
        "REQUIRES_ACTION": "措施要求",
        "OCCURS_ON": "发生于部件",
        "HAS_SYMPTOM": "具有症状",
        "CAUSED_BY": "由原因引起",
        "RESOLVED_BY": "通过措施处理",
        "DETECTED_BY": "通过方法检测"
    }

    rel_zh = relation_zh_map.get(relation, relation)

    query = f"""
    MATCH (h:Entity {{name: $head_name, type: $head_type}})
    MATCH (t:Entity {{name: $tail_name, type: $tail_type}})
    MERGE (h)-[r:{relation} {{
        doc_id: $doc_id,
        file_name: $file_name,
        relative_path: $relative_path,
        page_span: $page_span,
        page_num: $page_num,
        chunk_id: $chunk_id,
        source_sentence: $source_sentence
    }}]->(t)
    SET r.rel_zh = $rel_zh
    """

    tx.run(
        query,
        head_name=head_entity,
        head_type=head_type,
        tail_name=tail_entity,
        tail_type=tail_type,
        doc_id=doc_id,
        file_name=file_name,
        relative_path=relative_path,
        page_span=page_span,
        page_num=page_num,
        chunk_id=chunk_id,
        source_sentence=source_sentence,
        rel_zh=rel_zh
    )


# ========= 6. 主流程 =========
def main():
    print("开始读取抽取结果...")
    entities = load_jsonl(ENTITIES_FILE)
    relations = load_jsonl(RELATIONS_FILE)

    print(f"读取实体数: {len(entities)}")
    print(f"读取关系数: {len(relations)}")

    # 实体去重（按 name + type）
    unique_entities = {}
    for e in entities:
        key = (e["entity_name"], e["entity_type"])
        if key not in unique_entities:
            unique_entities[key] = e

    print(f"去重后实体数: {len(unique_entities)}")

    # 关系去重（按 头实体 + 关系 + 尾实体 + doc_id + chunk_id）
    unique_relations = {}
    for r in relations:
        key = (
            r["head_entity"],
            r["relation"],
            r["tail_entity"],
            r.get("doc_id", ""),
            r.get("chunk_id", "")
        )
        if key not in unique_relations:
            unique_relations[key] = r

    print(f"去重后关系数: {len(unique_relations)}")

    with driver.session() as session:
        print("创建约束...")
        session.execute_write(create_constraints)

        # 如果你想每次重建图谱，就保留
        print("清空旧图...")
        session.execute_write(clear_graph)

        print("开始导入节点...")
        for (entity_name, entity_type), _ in tqdm(unique_entities.items(), desc="导入节点"):
            session.execute_write(merge_entity, entity_name, entity_type)

        print("开始导入关系...")
        for _, r in tqdm(unique_relations.items(), desc="导入关系"):
            session.execute_write(merge_relation, r)

    print("\n图谱构建-v3.1完成。")
    print("你现在可以到 Neo4j Browser / Query 页面查看新图谱。")


if __name__ == "__main__":
    try:
        # 最小连接测试
        with driver.session() as session:
            result = session.run("RETURN 1 AS ok")
            print("Neo4j 连接测试:", result.single()["ok"])
        main()
    finally:
        driver.close()