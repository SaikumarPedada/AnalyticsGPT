from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class SessionStartResponse(BaseModel):
    session_id: str


class SessionEndResponse(BaseModel):
    message: str
    tokens_consumed: int


class MessageOut(BaseModel):
    message_id: int
    role: str
    content: str
    tokens: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    session_id: str
    title: Optional[str]
    session_start: Optional[datetime]
    session_end: Optional[datetime]
    tokens_consumed: int
    created_at: datetime

    model_config = {"from_attributes": True}


class WSMessage(BaseModel):
    """Shape of JSON sent back over WebSocket."""
    text: str
    tokens: int
    session_id: str
