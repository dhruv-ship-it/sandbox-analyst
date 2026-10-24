"""The agent: dataset profiling, events/traces, the answer schema, evidence checks, and the loop."""

from .answer import (
    AnswerItem,
    AnswerParseError,
    FinalAnswer,
    extract_format_placeholders,
    extract_json,
    match_names_to_format,
    parse_final_answer,
)
from .codeparse import extract_code
from .events import AgentEvent, EventEmitter, EventType, OnEvent, new_run_id
from .evidence import EvidenceResult, all_evidenced, check_evidence
from .loop import AgentResult, AttemptRecord, run_agent
from .profile import ColumnProfile, DatasetProfile, profile_csv, to_prompt_text
from .trace import TraceWriter

__all__ = [
    "ColumnProfile",
    "DatasetProfile",
    "profile_csv",
    "to_prompt_text",
    "AgentEvent",
    "EventType",
    "OnEvent",
    "EventEmitter",
    "new_run_id",
    "TraceWriter",
    "AnswerItem",
    "FinalAnswer",
    "AnswerParseError",
    "extract_json",
    "extract_format_placeholders",
    "match_names_to_format",
    "parse_final_answer",
    "EvidenceResult",
    "check_evidence",
    "all_evidenced",
    "extract_code",
    "run_agent",
    "AgentResult",
    "AttemptRecord",
]
