from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.agents.nodes import (
    router_node,
    dataset_node,
    planner_node,
    executor_node,
    retry_node,
    explanation_node,
    response_node,
)

MAX_RETRIES = 3


def should_retry(state: AgentState):
    """
    Retry only when ALL three conditions hold:
      1. There is an error
      2. It is NOT a fatal error (dataset missing/unreadable — replanning can't fix it)
      3. We haven't hit MAX_RETRIES yet
    """
    if (
        state.get("error")
        and not state.get("fatal_error", False)
        and state.get("retry_count", 0) < MAX_RETRIES
    ):
        return "retry"
    return "continue"


def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("router", router_node)
    builder.add_node("dataset", dataset_node)
    builder.add_node("planner", planner_node)
    builder.add_node("executor", executor_node)
    builder.add_node("retry_node", retry_node)
    builder.add_node("explanation", explanation_node)
    builder.add_node("response", response_node)

    builder.set_entry_point("router")

    builder.add_edge("router", "dataset")
    builder.add_edge("dataset", "planner")
    builder.add_edge("planner", "executor")

    builder.add_conditional_edges(
        "executor",
        should_retry,
        {
            "retry": "retry_node",
            "continue": "explanation",
        },
    )

    builder.add_edge("retry_node", "executor")
    builder.add_edge("explanation", "response")
    builder.add_edge("response", END)

    return builder.compile()


agent_graph = build_graph()