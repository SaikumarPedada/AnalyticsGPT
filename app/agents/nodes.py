from app.services.router_service import router_service
from app.services.planner_service import planner_service
from app.services.executor_service import executor_service
from app.services.explanation_service import explanation_service
from app.agents.state import AgentState
from app.services.llm_service import llm_service
from app.prompts import RETRY_PROMPT
from app.core.logging import get_logger

import pandas as pd
import json
import os

logger = get_logger(__name__)

# Errors that the retry loop can NEVER fix — fail fast instead of burning retries
_FATAL_PREFIXES = (
    "Dataset load failed",
    "Unsupported file type",
)


def _is_fatal(error: str) -> bool:
    return any(error.startswith(p) for p in _FATAL_PREFIXES)


def _ensure_openpyxl() -> None:
    """Install openpyxl at runtime if it is missing."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        logger.warning("openpyxl missing — installing automatically")
        import subprocess, sys, importlib
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "openpyxl", "-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        importlib.invalidate_caches()
        logger.info("openpyxl installed successfully")


async def router_node(state: dict):
    mode = await router_service.route(
        state["message"],
        state.get("mode"),
    )
    state["mode"] = mode
    return state


async def dataset_node(state: dict):
    file_path = state.get("file_path")

    if not file_path:
        state["df"] = None
        return state

    try:
        ext = os.path.splitext(file_path)[-1].lower()

        if ext == ".csv":
            try:
                df = pd.read_csv(file_path)
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding="latin1")

        elif ext in [".xlsx", ".xls"]:
            _ensure_openpyxl()                          # ← auto-install guard
            df = pd.read_excel(file_path, engine="openpyxl")

        else:
            raise ValueError(f"Unsupported file type: {ext}")

        state["df"] = df
        state["schema"] = ", ".join(df.columns)
        state["error"] = None
        state["fatal_error"] = False

    except Exception as e:
        msg = f"Dataset load failed: {e}"
        logger.error(msg)
        state["error"] = msg
        state["fatal_error"] = True   # ← tells graph to skip retry entirely
        state["df"] = None

    return state


async def planner_node(state: dict):
    # Skip planning if dataset loading already fatally failed
    if state.get("fatal_error"):
        return state

    plan = await planner_service.create_plan(
        db=None,
        user_id=state["user_id"],
        message=state["message"],
        mode=state["mode"],
        schema=state.get("schema", ""),
    )

    state["plan"] = plan
    state["steps"] = plan.get("steps", [])
    return state


async def executor_node(state: AgentState):
    # Hard stop: fatal errors (e.g. missing file, bad extension) cannot be
    # fixed by replanning — skip execution entirely.
    if state.get("fatal_error") or state.get("error"):
        return state

    df = state.get("df")
    plan = state.get("plan")
    mode = state.get("mode", "auto")
    query = state.get("message", "")

    logs: list = []

    async def stream(msg: str):
        logs.append(msg)

    try:
        result = await executor_service.execute(
            plan=plan,
            df=df,
            mode=mode,
            query=query,
            stream_callback=stream,
        )

        state["result"] = result
        state["logs"] = logs
        state["error"] = None

    except Exception as e:
        logger.exception("Executor failed")
        state["error"] = str(e)
        state["logs"] = logs

    return state


async def retry_node(state: dict):
    error = state.get("error")
    if not error:
        return state

    retry_count = state.get("retry_count", 0) + 1
    state["retry_count"] = retry_count
    logger.warning(f"Retry {retry_count} triggered. Error: {error}")

    message = state["message"]
    plan = state.get("plan")

    prompt = RETRY_PROMPT.format(
        message=message,
        plan=plan,
        error=error,
    )

    result = {}
    try:
        result = await llm_service.generate([
            {"role": "user", "content": prompt}
        ])

        raw = result["text"].strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        new_plan = json.loads(raw)

        state["plan"] = new_plan
        state["steps"] = new_plan.get("steps", [])
        state["error"] = None   # clear so executor gets a clean run

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(
            f"Retry plan parse failed: {e}. "
            f"Raw output: {result.get('text', '')[:200]}"
        )
        # Keep existing error; MAX_RETRIES guard will eventually exit the loop

    return state


async def explanation_node(state: dict):
    if state.get("error") or state.get("fatal_error"):
        state["explanation"] = ""
        return state

    steps = state.get("steps", [])
    if not steps:
        state["explanation"] = ""
        return state

    explanation = await explanation_service.generate(
        message=state.get("message"),
        steps=steps,
    )
    state["explanation"] = explanation
    return state


async def response_node(state: dict):
    error = state.get("error")

    if error:
        fatal = state.get("fatal_error", False)
        prefix = "⚠️ Could not load the dataset" if fatal else "⚠️ Could not complete the request after retries"
        state["final"] = f"{prefix}.\n\nError: {error}"
        return state

    result = state.get("result")
    explanation = state.get("explanation", "")

    if isinstance(result, dict):
        # Use indent=2 for readable, formatted JSON output
        result_text = json.dumps(result, indent=2)
    elif result is None:
        result_text = "(no result produced)"
    else:
        result_text = str(result)

    final_output = result_text
    if explanation:
        final_output += "\n\n🧠 Explanation:\n" + explanation

    state["final"] = final_output
    return state