from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ChatRequest:
    messages: tuple[Message, ...]
    tools: tuple[ToolDefinition, ...] = ()
    temperature: float = 0.0


@dataclass(frozen=True, slots=True)
class ChatResponse:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class RerankResult:
    index: int
    score: float
