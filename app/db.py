import logging

from neo4j import GraphDatabase
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

logger = logging.getLogger(__name__)

driver = GraphDatabase.driver(
    NEO4J_URI,
    auth=(NEO4J_USER, NEO4J_PASSWORD)
)


def run_query(query: str, params: dict | None = None):
    try:
        with driver.session() as session:
            result = session.run(query, params or {})
            return [record.data() for record in result]
    except Exception as exc:
        logger.exception("Neo4j 查询失败。query=%s, params=%s", query, params)
        raise RuntimeError("Neo4j 未连接，请检查数据库配置和服务状态。") from exc