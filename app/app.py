from flask import Flask, render_template, request, jsonify
import logging
from jinja2 import TemplateNotFound

from config import DEBUG, APP_HOST, APP_PORT
from graph_rag import graph_rag_answer
from services.graph_service import (
    get_graph_stats,
    query_entity_neighbors,
    get_local_graph_data,
    get_standard_local_graph_data,
    get_global_type_graph_data,
    get_full_graph_data,
    normalize_entity_name,
)
from services.qa_service import qa_query

app = Flask(__name__)
logger = logging.getLogger(__name__)


def _json_error(message: str, status_code: int = 500):
    return jsonify({"success": False, "message": message}), status_code


@app.route("/")
def index():
    try:
        stats = get_graph_stats()
        return render_template("index.html", stats=stats)
    except Exception:
        logger.exception("首页加载失败。")
        return render_template(
            "index.html",
            stats={"total_nodes": 0, "total_relations": 0, "entity_types": [], "relation_types": []},
            message="Neo4j 未连接，请检查数据库配置和服务状态。"
        )


@app.route("/entity", methods=["GET", "POST"])
def entity_query():
    entity_name = ""
    results = []
    message = ""

    try:
        if request.method == "POST":
            entity_name = request.form.get("entity_name", "").strip()
            if entity_name:
                results = query_entity_neighbors(entity_name)
    except Exception:
        logger.exception("/entity 查询异常。")
        results = []
        message = "查询失败，请检查 Neo4j 连接状态。"

    return render_template(
        "entity_query.html",
        entity_name=entity_name,
        results=results,
        message=message
    )


@app.route("/qa", methods=["GET", "POST"])
def qa():
    question = ""
    entity_name = ""
    query_type = ""
    results = []
    summary = ""

    try:
        if request.method == "POST":
            question = request.form.get("question", "").strip()
            if question:
                entity_name, query_type, results, summary = qa_query(question)
    except Exception:
        logger.exception("/qa 执行异常。")
        summary = "问答查询失败，请检查 Neo4j 连接和数据状态。"
        results = []

    return render_template(
        "qa.html",
        question=question,
        entity_name=entity_name,
        query_type=query_type,
        results=results,
        summary=summary
    )


@app.route("/graph_rag", methods=["GET", "POST"])
def graph_rag():
    result = {
        "question": "",
        "entity_name": "",
        "intent": "",
        "answer": "",
        "graph_results": [],
        "evidence_results": []
    }

    try:
        if request.method == "POST":
            question = request.form.get("question", "").strip()
            if question:
                result = graph_rag_answer(question)
            else:
                result["answer"] = "请输入问题。"
    except Exception:
        logger.exception("/graph_rag 执行异常。")
        result["answer"] = "GraphRAG 查询失败，请检查 Neo4j、关系文件与系统配置。"

    return render_template("graph_rag.html", result=result)


@app.route("/graph_view", methods=["GET", "POST"])
def graph_view():
    entity_name = ""
    graph_data = {"nodes": [], "edges": []}
    message = ""

    try:
        if request.method == "POST":
            entity_name = normalize_entity_name(request.form.get("entity_name", ""))
            if entity_name:
                graph_data = get_standard_local_graph_data(entity_name)
                if not graph_data["nodes"]:
                    message = f"未检索到与“{entity_name}”相关的局部图谱。"
            else:
                message = "请输入实体名称。"
    except Exception:
        logger.exception("/graph_view 执行异常。")
        graph_data = {"nodes": [], "edges": []}
        message = "图谱查询失败，请检查 Neo4j 连接状态。"

    return render_template(
        "graph_view.html",
        entity_name=entity_name,
        graph_data=graph_data,
        message=message
    )


@app.route("/api/graph_view", methods=["GET"])
def api_graph_view():
    try:
        entity_name = normalize_entity_name(request.args.get("entity_name", ""))
        if not entity_name:
            return _json_error("缺少参数 entity_name。", 400)
        graph_data = get_standard_local_graph_data(entity_name)
        return jsonify({"success": True, "message": "", **graph_data})
    except Exception:
        logger.exception("/api/graph_view 执行异常。")
        return _json_error("图谱查询失败，请检查数据库配置和服务状态。")


@app.route("/api/local_graph")
def api_local_graph():
    try:
        entity_name = request.args.get("entity_name", "").strip()
        if not entity_name:
            return _json_error("缺少实体名。", 400)
        graph_data = get_standard_local_graph_data(entity_name)
        return jsonify({"success": True, "message": "", **graph_data})
    except Exception:
        logger.exception("/api/local_graph 执行异常。")
        return _json_error("局部图查询失败，请检查数据库配置和服务状态。")


@app.route("/global_graph_view")
def global_graph_view():
    try:
        graph_data = get_global_type_graph_data()
        return render_template(
            "global_graph_view.html",
            graph_data=graph_data
        )
    except Exception:
        logger.exception("/global_graph_view 执行异常。")
        return render_template(
            "global_graph_view.html",
            graph_data={"nodes": [], "edges": []},
            message="全局图谱加载失败，请检查 Neo4j 连接状态。"
        )


@app.route("/global_graph_full")
def global_graph_full():
    try:
        graph_data = get_full_graph_data(top_n=120)
        return render_template(
            "global_graph_full.html",
            graph_data=graph_data
        )
    except Exception:
        logger.exception("/global_graph_full 执行异常。")
        return render_template(
            "global_graph_full.html",
            graph_data={
                "nodes": [],
                "edges": [],
                "recommended_node_ids": [],
                "entity_type_options": [],
                "relation_category_options": [],
                "total_node_count": 0,
                "total_edge_count": 0
            },
            message="全图加载失败，请检查 Neo4j 连接状态。"
        )


@app.route("/health")
def health():
    return {"status": "ok", "success": True}


@app.errorhandler(TemplateNotFound)
def handle_template_not_found(err):
    logger.exception("模板缺失：%s", err)
    return (
        "页面模板缺失，请检查 templates 目录是否完整。",
        500
    )


@app.errorhandler(Exception)
def handle_unexpected_error(err):
    logger.exception("未处理异常：%s", err)
    if request.path.startswith("/api/"):
        return _json_error("服务内部错误，请稍后重试。")
    return (
        "系统内部异常，请检查后端日志（Neo4j连接、数据文件、模板文件）。",
        500
    )


if __name__ == "__main__":
    app.run(debug=DEBUG, host=APP_HOST, port=APP_PORT, use_reloader=False)