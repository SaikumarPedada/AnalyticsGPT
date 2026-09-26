"""
Official Model Context Protocol (MCP) Server using FastMCP.
Exposes backend capabilities as standard MCP tools (@mcp.tool()).
"""
import io
import json
import os
import pandas as pd
from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    class FastMCP:
        def __init__(self, name: str):
            self.name = name
            self._tools = {}

        def tool(self):
            def decorator(func):
                self._tools[func.__name__] = func
                return func
            return decorator

from app.models import Dataset, ChatSession, Message
from app.services.qdrant_service import qdrant_service
from app.services.embedding_service import embedding_service
from app.services.executor_service import executor_service
from app.core.logging import get_logger

logger = get_logger(__name__)

# Instantiate FastMCP server instance
mcp_server = FastMCP("AnalyticsGPT-Server")


@mcp_server.tool()
async def search_past_memory(user_id: int, query: str) -> str:
    """
    Search historical conversational memory and user logs using Qdrant vector similarity search.
    """
    try:
        query_vec = embedding_service.embed(query)
        hits = qdrant_service.search(query_vec, user_id=user_id, limit=5)
        results = [{"role": h.get("role"), "content": h.get("content")} for h in hits]
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        logger.error(f"MCP search_past_memory failed: {e}")
        return f"Error searching memory: {e}"


@mcp_server.tool()
async def get_dataset_info(dataset_id: str) -> str:
    """
    Retrieve dataset metadata, schema, column data types, row count, and top 5 rows preview.
    """
    try:
        db_dataset = await Dataset.get_or_none(dataset_id=dataset_id)
        if not db_dataset:
            return f"Dataset '{dataset_id}' not found."

        ext = os.path.splitext(db_dataset.filename)[-1].lower()
        content = db_dataset.content

        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(content))
        elif ext in [".xlsx", ".xls"]:
            df = pd.read_excel(io.BytesIO(content))
        else:
            return f"Unsupported dataset extension '{ext}'."

        info = {
            "dataset_id": dataset_id,
            "filename": db_dataset.filename,
            "rows": len(df),
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "head": df.head(5).to_dict(orient="records"),
        }
        return json.dumps(info, indent=2, default=str)
    except Exception as e:
        logger.error(f"MCP get_dataset_info failed: {e}")
        return f"Error loading dataset info: {e}"


@mcp_server.tool()
async def list_user_sessions(user_id: int) -> str:
    """
    Fetch historical chat sessions for a specific user from PostgreSQL.
    """
    try:
        sessions = await ChatSession.filter(user_id=user_id).order_by("-created_at").limit(10)
        data = [
            {
                "session_id": s.session_id,
                "title": s.title,
                "created_at": s.created_at.isoformat(),
            }
            for s in sessions
        ]
        return json.dumps(data, indent=2)
    except Exception as e:
        logger.error(f"MCP list_user_sessions failed: {e}")
        return f"Error listing user sessions: {e}"


@mcp_server.tool()
async def execute_pandas_code(dataset_id: str, python_code: str) -> str:
    """
    Execute a dynamic Python/Pandas script against the uploaded dataset and return results or plots.
    """
    try:
        db_dataset = await Dataset.get_or_none(dataset_id=dataset_id)
        if not db_dataset:
            return f"Dataset '{dataset_id}' not found."

        ext = os.path.splitext(db_dataset.filename)[-1].lower()
        content = db_dataset.content

        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(content))
        elif ext in [".xlsx", ".xls"]:
            df = pd.read_excel(io.BytesIO(content))
        else:
            return f"Unsupported file type '{ext}'."

        plan = {"code": python_code}
        res = await executor_service.execute(plan=plan, df=df, mode="analytics", query="MCP execution")
        return json.dumps(res, indent=2, default=str)
    except Exception as e:
        logger.error(f"MCP execute_pandas_code failed: {e}")
        return f"Error executing code: {e}"
