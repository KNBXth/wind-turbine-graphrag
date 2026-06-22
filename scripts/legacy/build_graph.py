from pathlib import Path
import json
from neo4j import GraphDatabase
from tqdm import tqdm

# ========= 1. Neo4j 连接配置 =========
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "12345678"   # 改成你自己的密码

# ========= 2. 输入文件 =========
DATA_DIR = Path(r"E:\WORK\data\meta")
ENTITIES_FILE = DATA_DIR / "entities_v2.jsonl"
RELATIONS_FILE = DATA_DIR / "relations_v2.jsonl"

# ========= 3. 连接数据库 =========
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ========= 4. 建约束 / 索引 =========
def create_constraints(tx):
    # Neo4j 5.x 写法
    tx.run("CREATE CONSTRAINT entity_name_type IF NOT EXISTS FOR (n:Entity) REQUIRE (n.name, n.type) IS UNIQUE")

# ========= 5. 清空图（可选） =========
def clear_graph(tx):
    tx.run("MATCH (n) DETACH DELETE n")

# ========= 6. 创建节点 =========
def merge_entity(tx, entity_name, entity_type):
    query = """
    MERGE (n:Entity {name: $name, type: $type})
    ON CREATE SET
        n.created_at = datetime()
    """
    tx.run(query, name=entity_name, type=entity_type)

# ========= 7. 创建关系 =========
def merge_relation(tx, head_name, head_type, relation, tail_name, tail_type,
                   doc_id="", file_name="", page_num=None, chunk_id="", source_sentence=""):
    query = f"""
    MATCH (h:Entity {{name: $head_name, type: $head_type}})
    MATCH (t:Entity {{name: $tail_name, type: $tail_type}})
    MERGE (h)-[r:{relation} {{
        doc_id: $doc_id,
        file_name: $file_name,
        page_num: $page_num,
        chunk_id: $chunk_id,
        source_sentence: $source_sentence
    }}]->(t)
    ON CREATE SET
        r.created_at = datetime()
    """
    tx.run(
        query,
        head_name=head_name,
        head_type=head_type,
        tail_name=tail_name,
        tail_type=tail_type,
        doc_id=doc_id,
        file_name=file_name,
        page_num=page_num,
        chunk_id=chunk_id,
        source_sentence=source_sentence
    )

# ========= 8. 读取 JSONL =========
def load_jsonl(file_path):
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records

# ========= 9. 主流程 =========
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

    with driver.session() as session:
        print("创建约束...")
        session.execute_write(create_constraints)

        # 如果你想每次重建图谱，就打开这一行
        # print("清空旧图...")
        # session.execute_write(clear_graph)

        print("开始导入节点...")
        for (entity_name, entity_type), _ in tqdm(unique_entities.items(), desc="导入节点"):
            session.execute_write(merge_entity, entity_name, entity_type)

        print("开始导入关系...")
        for r in tqdm(relations, desc="导入关系"):
            try:
                session.execute_write(
                    merge_relation,
                    r["head_entity"],
                    r["head_type"],
                    r["relation"],
                    r["tail_entity"],
                    r["tail_type"],
                    r.get("doc_id", ""),
                    r.get("file_name", ""),
                    r.get("page_num", None),
                    r.get("chunk_id", ""),
                    r.get("source_sentence", "")
                )
            except Exception as e:
                print(f"关系导入失败: {r} -> {e}")

    print("\n图谱构建完成。")
    print("你现在可以到 Neo4j Browser 里查询图谱。")

if __name__ == "__main__":
    try:
        main()
    finally:
        driver.close()