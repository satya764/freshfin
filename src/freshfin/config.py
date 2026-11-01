"""Settings from environment variables (with an optional .env file) and the model list from models.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE lines into os.environ without overriding variables already set."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    sec_user_agent: str
    anthropic_api_key: str
    cache_dir: Path
    models_file: Path

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        return cls(
            sec_user_agent=os.environ.get("SEC_USER_AGENT", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            cache_dir=Path(os.environ.get("CACHE_DIR", "data/cache")),
            models_file=Path(os.environ.get("MODELS_FILE", "models.toml")),
        )


@dataclass(frozen=True)
class ModelSpec:
    name: str  # API model id, e.g. claude-haiku-5-5 or qwen3-16k
    label: str  # shown in reports
    provider: str  # "anthropic" or "openai_compatible"
    price_in: float = 0.0  # USD per million input tokens
    price_out: float = 0.0  # USD per million output tokens
    base_url: str = ""  # openai_compatible only
    api_key_env: str = ""  # openai_compatible only; env var holding the key, if any
    fresh_after: date | None = None  # filings on or before this date may be in the model's training data
    workers: int = 4  # parallel requests

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.price_in + output_tokens * self.price_out) / 1_000_000


def load_models(path: Path) -> dict[str, ModelSpec]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Copy models.example.toml to models.toml.")
    raw = tomllib.loads(path.read_text())
    models: dict[str, ModelSpec] = {}
    for entry in raw.get("model", []):
        entry = dict(entry)
        if isinstance(entry.get("fresh_after"), str):
            entry["fresh_after"] = date.fromisoformat(entry["fresh_after"])
        spec = ModelSpec(**entry)
        if spec.provider not in ("anthropic", "openai_compatible"):
            raise ValueError(f"{spec.name}: provider must be 'anthropic' or 'openai_compatible'")
        models[spec.name] = spec
    return models
