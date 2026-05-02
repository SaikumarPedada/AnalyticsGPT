from typing import TypedDict, List, Dict, Any, Optional


class AgentState(TypedDict, total=False):
    # Input
    user_id: int
    message: str
    mode: str
    file_path: Optional[str]

    # Dataset
    df: Any
    schema: str

    # Planning
    plan: Dict
    steps: List[Dict]

    # Execution
    result: Any
    logs: List[str]

    # Error handling
    error: Optional[str]
    fatal_error: bool    
    retry_count: int     

    # Output
    explanation: str
    final: str