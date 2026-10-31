from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(extra='ignore')
    role: str = Field(max_length=40)
    text: str = Field(default='', max_length=20000)
    attachments: list[Any] | dict[str, Any] | int | None = None


class TicketIn(BaseModel):
    # Outcome fields (verdict, punishment, violation, status, etc.) are discarded.
    model_config = ConfigDict(extra='ignore')
    kind: str = Field(max_length=40)
    messages: list[Message] = Field(max_length=100)
    ticket_id: str | None = Field(default=None, max_length=256)
    lang: str | None = Field(default=None, max_length=16)
    server_lang: str | None = Field(default=None, max_length=16)
    region: str | None = Field(default=None, max_length=80)
    reporter_hash: str | None = Field(default=None, max_length=256)
    reported_hash: str | None = Field(default=None, max_length=256)
    reported_nick: str | None = Field(default=None, max_length=100)
    rule_refs_raw: str | list[str] | None = None
    images_count: int | None = Field(default=None, ge=0, le=10000)
    created_at: str | None = Field(default=None, max_length=80)


class Citation(BaseModel):
    ref: str
    text: str
    section: str


class Extracted(BaseModel):
    nickname: str | None
    rule_refs: list[str]
    has_evidence: bool
    server: str | None


class DraftReply(BaseModel):
    lang: str
    text: str
    cited: list[Citation]


class TriageOut(BaseModel):
    lang: str
    category: str
    priority: Literal['p0', 'p1', 'p2', 'p3']
    is_spam_or_duplicate: bool
    extracted: Extracted
    draft_reply: DraftReply
    needs_human: bool
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]


class QueueAction(BaseModel):
    action: Literal['edit', 'send', 'escalate']
    draft_text: str | None = Field(default=None, max_length=20000)
