"""Chat sessions with tool use for two kinds of API: Anthropic Messages and OpenAI-style chat
(Ollama, Groq, OpenRouter, ...). Plain HTTP, no SDKs, so the benchmark has no dependencies.

A session keeps its own message history in its provider's format:
    session = client.start(model, system, question, tools)
    reply = session.step()                      # one model call
    session.add_tool_results([(id, text), ...])  # then step() again
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
RETRY_STATUS = {429, 500, 502, 503, 504, 529}


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class Session(Protocol):
    def step(self) -> Reply: ...
    def add_tool_results(self, results: list[tuple[str, str]]) -> None: ...


class Client(Protocol):
    def start(self, model: str, system: str, user: str, tools: list[dict] | None) -> Session: ...


def post_json(url: str, body: dict, headers: dict[str, str], timeout: float, retries: int = 4) -> dict:
    data = json.dumps(body).encode()
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:500]
            if err.code in RETRY_STATUS and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise LLMError(f"HTTP {err.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as err:
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise LLMError(str(err)) from None
    raise LLMError("unreachable")


# ---- Anthropic ----------------------------------------------------------------


class AnthropicClient:
    def __init__(self, api_key: str, max_tokens: int = 4096, timeout: float = 120.0):
        if not api_key:
            raise ValueError("Set ANTHROPIC_API_KEY to run Claude models.")
        self.headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
        self.max_tokens = max_tokens  # room for thinking on models that think by default
        self.timeout = timeout

    def start(self, model, system, user, tools=None) -> AnthropicSession:
        return AnthropicSession(self, model, system, user, tools)


class AnthropicSession:
    def __init__(self, client: AnthropicClient, model: str, system: str, user: str, tools: list[dict] | None):
        self.client, self.model, self.system, self.tools = client, model, system, tools
        self.messages: list[dict] = [{"role": "user", "content": user}]

    def step(self) -> Reply:
        body: dict[str, Any] = {
            "model": self.model,
            "system": self.system,
            "messages": self.messages,
            "max_tokens": self.client.max_tokens,
        }
        if self.tools:
            body["tools"] = self.tools
        data = post_json(ANTHROPIC_URL, body, self.client.headers, self.client.timeout)
        content = data.get("content", [])
        self.messages.append({"role": "assistant", "content": content})
        usage = data.get("usage", {})
        return Reply(
            text="".join(b.get("text", "") for b in content if b.get("type") == "text").strip(),
            tool_calls=[
                ToolCall(b["id"], b["name"], b.get("input") or {}) for b in content if b.get("type") == "tool_use"
            ],
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    def add_tool_results(self, results):
        self.messages.append(
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": i, "content": text} for i, text in results],
            }
        )


# ---- OpenAI-compatible (Ollama and others) -------------------------------------------


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str = "", max_tokens: int = 2048, timeout: float = 600.0):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self.max_tokens = max_tokens
        self.timeout = timeout

    def start(self, model, system, user, tools=None) -> OpenAISession:
        if model.startswith("qwen3"):
            system += " /no_think"  # Qwen3 skips its long reasoning trace with this switch
        return OpenAISession(self, model, system, user, tools)


class OpenAISession:
    def __init__(self, client: OpenAICompatibleClient, model: str, system: str, user: str, tools: list[dict] | None):
        self.client, self.model = client, model
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],
                },
            }
            for t in tools or []
        ]
        self.messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def step(self) -> Reply:
        body: dict[str, Any] = {"model": self.model, "messages": self.messages, "max_tokens": self.client.max_tokens}
        if self.tools:
            body["tools"] = self.tools
        data = post_json(self.client.url, body, self.client.headers, self.client.timeout)
        message = data["choices"][0]["message"]
        calls = []
        for call in message.get("tool_calls") or []:
            args = call["function"].get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except json.JSONDecodeError:
                    args = {}
            calls.append(ToolCall(call.get("id") or f"call_{uuid.uuid4().hex[:12]}", call["function"]["name"], args))
        entry: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
        if calls:
            entry["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                for c in calls
            ]
        self.messages.append(entry)
        usage = data.get("usage") or {}
        return Reply(
            text=(message.get("content") or "").strip(),
            tool_calls=calls,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    def add_tool_results(self, results):
        for call_id, text in results:
            self.messages.append({"role": "tool", "tool_call_id": call_id, "content": text})
