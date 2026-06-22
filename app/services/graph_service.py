from collections import defaultdict

from db import run_query
from mappings import (
    ENTITY_TYPE_MAP,
    RELATION_TYPE_MAP,
    GRAPH_RELATION_SHORT_MAP,
    GRAPH_RELATION_CATEGORY_MAP,
    NODE_COLOR_MAP,
    TYPE_NODE_COLOR_MAP,
    GRAPH_RELATION_PRIORITY,
    ENTITY_ALIAS_MAP,
)


def entity_type_to_zh(entity_type: str) -> str:
    if not entity_type:
        return ""
    return ENTITY_TYPE_MAP.get(entity_type, entity_type)


def zh_entity_type(entity_type: str) -> str:
    return entity_type_to_zh(entity_type)


def zh_relation(rel_zh: str | None, rel_en: str | None) -> str:
    if rel_zh:
        return rel_zh
    return RELATION_TYPE_MAP.get(rel_en or "", rel_en or "")


def normalize_entity_name(name: str) -> str:
    if not name:
        return ""
    name = str(name).strip().replace("　", " ")
    return ENTITY_ALIAS_MAP.get(name, name)


def shorten_text(text: str | None, max_len: int = 90) -> str:
    if not text:
        return ""
    text = " ".join(str(text).split())
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def get_page_display(row: dict) -> str:
    page_span = row.get("page_span")
    page_num = row.get("page_num")
    if page_span not in (None, ""):
        return str(page_span)
    if page_num not in (None, ""):
        return str(page_num)
    return ""


def deduplicate_records(records, group_keys):
    grouped = {}

    for row in records:
        key = tuple(row.get(k, "") for k in group_keys)

        if key not in grouped:
            grouped[key] = {
                "source_name": row.get("source_name", ""),
                "source_type": zh_entity_type(row.get("source_type", "")),
                "relation_zh": zh_relation(row.get("relation_zh", ""), row.get("relation_en", "")),
                "target_name": row.get("target_name", ""),
                "target_type": zh_entity_type(row.get("target_type", "")),
                "evidences": []
            }

        evidence = {
            "file_name": row.get("file_name", ""),
            "page_num": row.get("page_num", ""),
            "page_span": row.get("page_span", ""),
            "page_display": get_page_display(row),
            "source_sentence": shorten_text(row.get("source_sentence", ""), 100)
        }

        if evidence not in grouped[key]["evidences"]:
            grouped[key]["evidences"].append(evidence)

    results = []
    for _, value in grouped.items():
        value["evidences"] = value["evidences"][:3]
        results.append(value)

    return results


def get_graph_stats():
    node_query = """
    MATCH (n:Entity)
    RETURN count(n) AS total_nodes
    """
    rel_query = """
    MATCH ()-[r]->()
    RETURN count(r) AS total_relations
    """
    entity_type_query = """
    MATCH (n:Entity)
    RETURN n.type AS entity_type, count(*) AS cnt
    ORDER BY cnt DESC
    """
    relation_type_query = """
    MATCH ()-[r]->()
    RETURN type(r) AS relation_type, count(*) AS cnt
    ORDER BY cnt DESC
    """

    total_nodes = run_query(node_query)[0]["total_nodes"]
    total_relations = run_query(rel_query)[0]["total_relations"]

    entity_types_raw = run_query(entity_type_query)
    relation_types_raw = run_query(relation_type_query)

    entity_types = []
    for row in entity_types_raw:
        entity_types.append({
            "entity_type": entity_type_to_zh(row["entity_type"]),
            "cnt": row["cnt"]
        })

    relation_types = []
    for row in relation_types_raw:
        relation_types.append({
            "relation_type": RELATION_TYPE_MAP.get(row["relation_type"], row["relation_type"]),
            "cnt": row["cnt"]
        })

    return {
        "total_nodes": total_nodes,
        "total_relations": total_relations,
        "entity_types": entity_types,
        "relation_types": relation_types
    }


def query_entity_neighbors(entity_name: str):
    entity_name = normalize_entity_name(entity_name)
    query = """
    MATCH (n:Entity {name: $entity_name})-[r]->(m:Entity)
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
    ORDER BY relation_en, target_name
    LIMIT 200
    """
    rows = run_query(query, {"entity_name": entity_name})
    return deduplicate_records(
        rows,
        group_keys=["source_name", "relation_en", "target_name"]
    )


def get_standard_local_graph_data(entity_name: str):
    entity_name = normalize_entity_name(entity_name)

    query = """
    MATCH (n:Entity {name: $entity_name})-[r]->(m:Entity)
    RETURN
        n.name AS source_name,
        n.type AS source_type,
        m.name AS target_name,
        m.type AS target_type,
        type(r) AS relation_en,
        coalesce(r.rel_zh, type(r)) AS relation_zh,
        r.file_name AS file_name,
        r.page_num AS page_num,
        r.page_span AS page_span,
        r.source_sentence AS source_sentence
    """

    rows = run_query(query, {"entity_name": entity_name})

    if not rows:
        return {"nodes": [], "edges": []}

    node_map = {}
    edge_group = defaultdict(list)

    for row in rows:
        s = row.get("source_name", "") or ""
        t = row.get("target_name", "") or ""
        s_type = row.get("source_type", "") or "Entity"
        t_type = row.get("target_type", "") or "Entity"
        rel_en = row.get("relation_en", "") or ""
        rel_zh = row.get("relation_zh", "") or RELATION_TYPE_MAP.get(rel_en, rel_en)

        if s not in node_map:
            node_map[s] = {
                "id": s,
                "label": s,
                "entity_type": s_type,
                "entity_type_zh": ENTITY_TYPE_MAP.get(s_type, s_type),
                "is_center": (s == entity_name)
            }

        if t not in node_map:
            node_map[t] = {
                "id": t,
                "label": t,
                "entity_type": t_type,
                "entity_type_zh": ENTITY_TYPE_MAP.get(t_type, t_type),
                "is_center": (t == entity_name)
            }

        edge_key = (s, rel_zh, t)
        edge_group[edge_key].append({
            "file_name": row.get("file_name", "") or "",
            "page_num": row.get("page_num", "") or "",
            "page_span": row.get("page_span", "") or "",
            "page_display": get_page_display(row),
            "source_sentence": row.get("source_sentence", "") or ""
        })

    nodes = []
    for node_id, node in node_map.items():
        node_type = node["entity_type"]
        color = NODE_COLOR_MAP.get(node_type, "#9AA5B1")

        if node["is_center"]:
            nodes.append({
                "id": node["id"],
                "label": node["label"],
                "entity_type": node["entity_type"],
                "entity_type_zh": node["entity_type_zh"],
                "is_center": True,
                "degree": 0,
                "size": 38,
                "shape": "dot",
                "borderWidth": 4,
                "color": {
                    "background": "#d9ecff",
                    "border": "#1f4f82",
                    "highlight": {
                        "background": "#d9ecff",
                        "border": "#163a63"
                    }
                },
                "font": {
                    "color": "#1f4f82",
                    "size": 26,
                    "face": "Microsoft YaHei",
                    "strokeWidth": 0
                }
            })
        else:
            nodes.append({
                "id": node["id"],
                "label": node["label"],
                "entity_type": node["entity_type"],
                "entity_type_zh": node["entity_type_zh"],
                "is_center": False,
                "degree": 0,
                "size": 26,
                "shape": "dot",
                "borderWidth": 2,
                "color": {
                    "background": color,
                    "border": "#4b5b6b",
                    "highlight": {
                        "background": color,
                        "border": "#1f4f82"
                    }
                },
                "font": {
                    "color": "#1f2937",
                    "size": 18,
                    "face": "Microsoft YaHei",
                    "strokeWidth": 0
                }
            })

    edges = []
    for idx, ((s, rel_zh, t), sources) in enumerate(edge_group.items(), start=1):
        rel_short = GRAPH_RELATION_SHORT_MAP.get(rel_zh, rel_zh)
        rel_category = GRAPH_RELATION_CATEGORY_MAP.get(rel_zh, "其他")

        edges.append({
            "id": f"local_edge_{idx}",
            "from": s,
            "to": t,
            "label": rel_short,
            "relation_full": rel_zh,
            "relation_category": rel_category,
            "source_count": len(sources),
            "sources": sources,
            "arrows": "to",
            "width": 3
        })

    return {
        "nodes": nodes,
        "edges": edges
    }


def get_local_graph_data(entity_name: str, limit: int = 40, max_edges: int = 12):
    entity_name = normalize_entity_name(entity_name)

    query_out = """
    MATCH (n:Entity {name: $entity_name})-[r]->(m:Entity)
    RETURN
        n.name AS source_name,
        n.type AS source_type,
        m.name AS target_name,
        m.type AS target_type,
        type(r) AS relation_en,
        coalesce(r.rel_zh, type(r)) AS relation_zh,
        r.file_name AS file_name,
        r.page_num AS page_num,
        r.page_span AS page_span,
        r.source_sentence AS source_sentence
    LIMIT $limit
    """

    query_in = """
    MATCH (n:Entity)-[r]->(m:Entity {name: $entity_name})
    RETURN
        n.name AS source_name,
        n.type AS source_type,
        m.name AS target_name,
        m.type AS target_type,
        type(r) AS relation_en,
        coalesce(r.rel_zh, type(r)) AS relation_zh,
        r.file_name AS file_name,
        r.page_num AS page_num,
        r.page_span AS page_span,
        r.source_sentence AS source_sentence
    LIMIT $limit
    """

    rows_out = run_query(query_out, {"entity_name": entity_name, "limit": limit})
    rows_in = run_query(query_in, {"entity_name": entity_name, "limit": limit})
    rows = rows_out + rows_in

    if not rows:
        return {"center": entity_name, "nodes": [], "edges": []}

    edge_group = defaultdict(list)

    for row in rows:
        s = row.get("source_name", "")
        t = row.get("target_name", "")
        rel_zh = row.get("relation_zh") or RELATION_TYPE_MAP.get(
            row.get("relation_en", ""),
            row.get("relation_en", "相关")
        )
        key = (s, rel_zh, t)
        edge_group[key].append(row)

    merged_edges = []

    for (s, rel_zh, t), group in edge_group.items():
        sources = []
        seen_source = set()

        for g in group:
            file_name = g.get("file_name", "") or ""
            page_display = get_page_display(g)
            sentence = g.get("source_sentence", "") or ""
            src_key = (file_name, page_display, sentence)

            if src_key not in seen_source:
                sources.append({
                    "file_name": file_name,
                    "page_num": g.get("page_num", "") or "",
                    "page_span": g.get("page_span", "") or "",
                    "page_display": page_display,
                    "source_sentence": sentence
                })
                seen_source.add(src_key)

        short_label = GRAPH_RELATION_SHORT_MAP.get(rel_zh, rel_zh)
        relation_category = GRAPH_RELATION_CATEGORY_MAP.get(rel_zh, "其他")
        priority = GRAPH_RELATION_PRIORITY.get(rel_zh, 10)
        center_bonus = 20 if s == entity_name or t == entity_name else 0
        source_bonus = min(len(sources), 5)
        score = priority + center_bonus + source_bonus

        merged_edges.append({
            "from": s,
            "to": t,
            "relation_zh": rel_zh,
            "relation_short": short_label,
            "relation_category": relation_category,
            "score": score,
            "sources": sources,
            "source_count": len(sources)
        })

    merged_edges = sorted(
        merged_edges,
        key=lambda x: (x["score"], x["source_count"]),
        reverse=True
    )

    selected_edges = merged_edges[:max_edges]

    node_map = {}
    name_type_map = {}

    for row in rows:
        if row.get("source_name"):
            name_type_map[row["source_name"]] = row.get("source_type", "Entity")
        if row.get("target_name"):
            name_type_map[row["target_name"]] = row.get("target_type", "Entity")

    def add_node(name, ntype):
        if not name:
            return
        if name not in node_map:
            color = NODE_COLOR_MAP.get(ntype, "#9AA5B1")
            node_map[name] = {
                "id": name,
                "label": name,
                "entity_type": ntype or "Entity",
                "entity_type_zh": entity_type_to_zh(ntype or "Entity"),
                "color": {
                    "background": color,
                    "border": "#5b6b7f",
                    "highlight": {
                        "background": color,
                        "border": "#1f4f82"
                    }
                },
                "borderWidth": 2,
                "font": {
                    "color": "#1f2937",
                    "size": 18,
                    "face": "Microsoft YaHei",
                    "strokeWidth": 0
                }
            }

    add_node(entity_name, name_type_map.get(entity_name, "Entity"))

    for e in selected_edges:
        add_node(e["from"], name_type_map.get(e["from"], "Entity"))
        add_node(e["to"], name_type_map.get(e["to"], "Entity"))

    if entity_name in node_map:
        node_map[entity_name]["color"] = {
            "background": "#D9E8F6",
            "border": "#1F4F82",
            "highlight": {
                "background": "#D9E8F6",
                "border": "#163A63"
            }
        }
        node_map[entity_name]["font"] = {
            "color": "#163A63",
            "size": 22,
            "face": "Microsoft YaHei",
            "strokeWidth": 0
        }
        node_map[entity_name]["borderWidth"] = 4
        node_map[entity_name]["size"] = 38

    edges = []
    edge_id = 1
    for e in selected_edges:
        edges.append({
            "id": f"e{edge_id}",
            "from": e["from"],
            "to": e["to"],
            "label": e["relation_short"],
            "relation_full": e["relation_zh"],
            "relation_category": e["relation_category"],
            "arrows": "to",
            "width": 2 + min(e["source_count"], 3),
            "sources": e["sources"],
            "source_count": e["source_count"]
        })
        edge_id += 1

    return {
        "center": entity_name,
        "nodes": list(node_map.values()),
        "edges": edges
    }


def get_global_type_graph_data():
    query = """
    MATCH (n:Entity)-[r]->(m:Entity)
    RETURN
        n.type AS source_type,
        type(r) AS relation_type,
        m.type AS target_type,
        count(*) AS rel_count
    ORDER BY rel_count DESC
    """

    rows = run_query(query, {})

    if not rows:
        return {"nodes": [], "edges": []}

    node_map = {}
    edge_list = []

    for row in rows:
        source_type_en = row.get("source_type", "")
        target_type_en = row.get("target_type", "")
        relation_en = row.get("relation_type", "")
        rel_count = int(row.get("rel_count", 0))

        source_type_zh = ENTITY_TYPE_MAP.get(source_type_en, source_type_en)
        target_type_zh = ENTITY_TYPE_MAP.get(target_type_en, target_type_en)
        relation_zh = RELATION_TYPE_MAP.get(relation_en, relation_en)

        if source_type_zh not in node_map:
            node_map[source_type_zh] = {
                "id": source_type_zh,
                "label": source_type_zh,
                "color": {
                    "background": TYPE_NODE_COLOR_MAP.get(source_type_zh, "#9AA5B1"),
                    "border": "#44556b",
                    "highlight": {
                        "background": TYPE_NODE_COLOR_MAP.get(source_type_zh, "#9AA5B1"),
                        "border": "#1f4f82"
                    }
                },
                "font": {
                    "color": "#1f2937",
                    "size": 20,
                    "face": "Microsoft YaHei",
                    "strokeWidth": 0
                },
                "borderWidth": 2,
                "shape": "dot",
                "size": 32
            }

        if target_type_zh not in node_map:
            node_map[target_type_zh] = {
                "id": target_type_zh,
                "label": target_type_zh,
                "color": {
                    "background": TYPE_NODE_COLOR_MAP.get(target_type_zh, "#9AA5B1"),
                    "border": "#44556b",
                    "highlight": {
                        "background": TYPE_NODE_COLOR_MAP.get(target_type_zh, "#9AA5B1"),
                        "border": "#1f4f82"
                    }
                },
                "font": {
                    "color": "#1f2937",
                    "size": 20,
                    "face": "Microsoft YaHei",
                    "strokeWidth": 0
                },
                "borderWidth": 2,
                "shape": "dot",
                "size": 32
            }

        edge_list.append({
            "from": source_type_zh,
            "to": target_type_zh,
            "relation_zh": relation_zh,
            "relation_en": relation_en,
            "count": rel_count
        })

    max_count = max(e["count"] for e in edge_list) if edge_list else 1

    edges = []
    for idx, e in enumerate(edge_list, start=1):
        width = 2 + (e["count"] / max_count) * 6
        edges.append({
            "id": f"tg{idx}",
            "from": e["from"],
            "to": e["to"],
            "label": f'{e["relation_zh"]}（{e["count"]}）',
            "relation_zh": e["relation_zh"],
            "relation_en": e["relation_en"],
            "count": e["count"],
            "arrows": "to",
            "width": round(width, 2)
        })

    return {
        "nodes": list(node_map.values()),
        "edges": edges
    }


def get_full_graph_data(top_n: int = 120):
    query = """
    MATCH (n:Entity)-[r]->(m:Entity)
    RETURN
        n.name AS source_name,
        n.type AS source_type,
        m.name AS target_name,
        m.type AS target_type,
        type(r) AS relation_en,
        coalesce(r.rel_zh, type(r)) AS relation_zh,
        r.file_name AS file_name,
        r.page_num AS page_num,
        r.page_span AS page_span,
        r.source_sentence AS source_sentence
    """

    rows = run_query(query, {})

    if not rows:
        return {
            "nodes": [],
            "edges": [],
            "recommended_node_ids": [],
            "entity_type_options": [],
            "relation_category_options": [],
            "total_node_count": 0,
            "total_edge_count": 0
        }

    edge_group = defaultdict(list)
    node_type_map = {}
    degree_map = defaultdict(int)

    for row in rows:
        s = row.get("source_name", "") or ""
        t = row.get("target_name", "") or ""
        s_type = row.get("source_type", "") or "Entity"
        t_type = row.get("target_type", "") or "Entity"
        rel_zh = row.get("relation_zh") or RELATION_TYPE_MAP.get(
            row.get("relation_en", ""),
            row.get("relation_en", "相关")
        )

        node_type_map[s] = s_type
        node_type_map[t] = t_type

        if s:
            degree_map[s] += 1
        if t:
            degree_map[t] += 1

        key = (s, rel_zh, t)
        edge_group[key].append(row)

    max_degree = max(degree_map.values()) if degree_map else 1
    nodes = []

    for node_name, node_type in node_type_map.items():
        degree = degree_map.get(node_name, 1)
        size = 18 + (degree / max_degree) * 22

        color = NODE_COLOR_MAP.get(node_type, "#9AA5B1")

        nodes.append({
            "id": node_name,
            "label": node_name,
            "entity_type": node_type,
            "entity_type_zh": entity_type_to_zh(node_type),
            "degree": degree,
            "size": round(size, 2),
            "color": {
                "background": color,
                "border": "#4b5b6b",
                "highlight": {
                    "background": color,
                    "border": "#163A63"
                }
            },
            "borderWidth": 2,
            "font": {
                "color": "#1f2937",
                "size": 16 if size < 28 else 18,
                "face": "Microsoft YaHei",
                "strokeWidth": 0
            }
        })

    merged_edges = []
    relation_category_options = set()

    for (s, rel_zh, t), group in edge_group.items():
        sources = []
        seen = set()

        for g in group:
            file_name = g.get("file_name", "") or ""
            page_display = get_page_display(g)
            sentence = g.get("source_sentence", "") or ""
            src_key = (file_name, page_display, sentence)

            if src_key not in seen:
                sources.append({
                    "file_name": file_name,
                    "page_num": g.get("page_num", "") or "",
                    "page_span": g.get("page_span", "") or "",
                    "page_display": page_display,
                    "source_sentence": sentence
                })
                seen.add(src_key)

        relation_short = GRAPH_RELATION_SHORT_MAP.get(rel_zh, rel_zh)
        relation_category = GRAPH_RELATION_CATEGORY_MAP.get(rel_zh, "其他")
        relation_category_options.add(relation_category)

        merged_edges.append({
            "from": s,
            "to": t,
            "relation_zh": rel_zh,
            "relation_short": relation_short,
            "relation_category": relation_category,
            "source_count": len(sources),
            "sources": sources
        })

    max_source_count = max([e["source_count"] for e in merged_edges], default=1)

    edges = []
    for idx, e in enumerate(merged_edges, start=1):
        width = 1.5 + (e["source_count"] / max_source_count) * 4.5
        edges.append({
            "id": f"edge_{idx}",
            "from": e["from"],
            "to": e["to"],
            "label": e["relation_short"],
            "relation_full": e["relation_zh"],
            "relation_category": e["relation_category"],
            "source_count": e["source_count"],
            "sources": e["sources"],
            "width": round(width, 2),
            "arrows": "to"
        })

    sorted_nodes = sorted(nodes, key=lambda x: x["degree"], reverse=True)
    recommended_node_ids = [n["id"] for n in sorted_nodes[:top_n]]

    entity_type_options = sorted(list({entity_type_to_zh(v) for v in node_type_map.values()}))
    relation_category_options = sorted(list(relation_category_options))

    return {
        "nodes": nodes,
        "edges": edges,
        "recommended_node_ids": recommended_node_ids,
        "entity_type_options": entity_type_options,
        "relation_category_options": relation_category_options,
        "total_node_count": len(nodes),
        "total_edge_count": len(edges)
    }