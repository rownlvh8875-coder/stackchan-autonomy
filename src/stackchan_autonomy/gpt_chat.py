"""Explicit paid text replies; no hardware, media, tool execution or saved dialogue."""

import asyncio
import re
import time

from openai import AsyncOpenAI, DefaultAsyncHttpxClient, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .async_storage import AsyncStorage, finish_cleanup
from .budget import SQLiteRequestBudget
from .private_logging import private_library_logs
from .settings import Settings
from .state_store import StateUnavailable

_CODES = frozenset(
    {
        "PC_GPT_CONFIG_REQUIRED",
        "PC_GPT_INVALID_QUESTION",
        "PC_GPT_BUDGET_EXHAUSTED",
        "PC_GPT_STORAGE_UNAVAILABLE",
        "PC_GPT_UNAVAILABLE",
    }
)
_INSTRUCTIONS = (
    "You are a helpful Korean desktop robot assistant. Answer naturally in Korean, "
    "usually in one to three short sentences. Be clear and honest about uncertainty. "
    "You receive text questions, not direct camera, microphone or robot state. "
    "Do not claim to observe or control hardware. This is a separate API conversation; "
    "do not claim access to a ChatGPT or Codex chat, files or its memory. "
    "Return the answer in the required JSON schema."
)


class GPTChatError(Exception):
    def __init__(self, code: str):
        self.code = code if code in _CODES else "PC_GPT_UNAVAILABLE"
        super().__init__(self.code)


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    answer: str = Field(min_length=1, max_length=800)


def _text(value: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError
    value = value.strip()
    if not 1 <= len(value) <= maximum or any(
        ord(c) < 32 and c not in "\t\n\r" or ord(c) == 127 for c in value
    ):
        raise ValueError
    value.encode("utf-8")
    return value


def validate_gpt_settings(settings: Settings, *, require_key: bool = True):
    if (
        not settings.cloud_enabled
        or not isinstance(settings.openai_model, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", settings.openai_model)
    ):
        raise GPTChatError("PC_GPT_CONFIG_REQUIRED")
    if require_key:
        key = settings.api_key.get_secret_value() if settings.api_key else ""
        if (
            not key
            or len(key) > 8192
            or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in key)
        ):
            raise GPTChatError("PC_GPT_CONFIG_REQUIRED")


class GPTChat:
    def __init__(self, settings: Settings, *, client=None, clock=time.time):
        validate_gpt_settings(settings, require_key=client is None)
        if client is None:
            key = settings.api_key.get_secret_value()
            with private_library_logs():
                client = AsyncOpenAI(
                    api_key=key,
                    base_url="https://api.openai.com/v1",
                    max_retries=0,
                    timeout=settings.operation_timeout_s,
                    http_client=DefaultAsyncHttpxClient(follow_redirects=False),
                )
        self.settings = settings
        self.client = client
        self.clock = clock
        self.budget = SQLiteRequestBudget(settings)
        self._storage = AsyncStorage()
        self._lock = asyncio.Lock()
        self._history: list[dict[str, str]] = []
        self._closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()

    async def aclose(self):
        self._closed = True

        async def close():
            try:
                await self._storage.aclose()
            finally:
                self._history.clear()
                await self.client.close()

        await finish_cleanup(asyncio.create_task(close()))

    async def ask(self, question: str) -> dict[str, object]:
        try:
            question = _text(question, 1200)
        except (ValueError, TypeError):
            raise GPTChatError("PC_GPT_INVALID_QUESTION") from None
        async with self._lock:
            if self._closed:
                raise GPTChatError("PC_GPT_UNAVAILABLE")
            with private_library_logs():
                return await self._ask(question)

    async def _ask(self, question: str) -> dict[str, object]:
        try:
            reserved = await self._storage.call(self.budget.reserve, self.clock())
        except StateUnavailable:
            raise GPTChatError("PC_GPT_STORAGE_UNAVAILABLE") from None
        if not reserved:
            raise GPTChatError("PC_GPT_BUDGET_EXHAUSTED")
        reasoning = (
            {}
            if self.settings.gpt_reasoning_effort is None
            else {"reasoning": {"effort": self.settings.gpt_reasoning_effort}}
        )
        try:
            response = await asyncio.wait_for(
                self.client.responses.create(
                    model=self.settings.openai_model,
                    instructions=_INSTRUCTIONS,
                    input=[*self._history, {"role": "user", "content": question}],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "robot_gpt_answer",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {"answer": {"type": "string"}},
                                "required": ["answer"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    store=False,
                    max_output_tokens=600,
                    timeout=self.settings.operation_timeout_s,
                    **reasoning,
                ),
                timeout=self.settings.operation_timeout_s,
            )
            if response.usage:
                await self._storage.call(
                    self.budget.record_usage,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
            if response.status != "completed" or any(
                block.type == "refusal"
                for item in response.output
                for block in getattr(item, "content", [])
            ):
                raise ValueError
            answer = _text(_Answer.model_validate_json(response.output_text).answer, 800)
        except StateUnavailable:
            raise GPTChatError("PC_GPT_STORAGE_UNAVAILABLE") from None
        except (OpenAIError, ValidationError, ValueError, TypeError, TimeoutError):
            try:
                await self._storage.call(self.budget.record_usage, failed=True)
            except StateUnavailable:
                pass
            raise GPTChatError("PC_GPT_UNAVAILABLE") from None
        self._history.extend(
            [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        )
        del self._history[:-6]
        return {
            "service": "stackchan-gpt",
            "provider": "openai_responses",
            "model": self.settings.openai_model,
            "answer": answer,
            "robot_control_available": False,
        }
