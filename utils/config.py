"""Central configuration. Secrets come from environment / .env only."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("QUERYMATE_DATA_DIR", ROOT / ".querymate"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_DB_PATH = DATA_DIR / "sample_ecommerce.db"
PREFS_PATH = DATA_DIR / "preferences.json"
SAMPLE_CONNECTION_ID = "sample"


def metadata_url() -> str:
    return os.getenv("QUERYMATE_METADATA_URL") or f"sqlite:///{DATA_DIR / 'metadata.db'}"


@dataclass
class Preferences:
    """Non-secret user preferences. Persisted to preferences.json."""
    result_limit: int = int(os.getenv("QUERYMATE_RESULT_LIMIT", "1000"))
    query_timeout: int = int(os.getenv("QUERYMATE_QUERY_TIMEOUT", "30"))
    ai_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    max_correction_attempts: int = 2
    schema_prompt_table_limit: int = 25

    @classmethod
    def load(cls) -> "Preferences":
        prefs = cls()
        if PREFS_PATH.exists():
            try:
                data = json.loads(PREFS_PATH.read_text())
                for k, v in data.items():
                    if hasattr(prefs, k):
                        setattr(prefs, k, type(getattr(prefs, k))(v))
            except Exception:
                pass  # corrupt prefs file -> defaults
        return prefs

    def save(self) -> None:
        PREFS_PATH.write_text(json.dumps(asdict(self), indent=2))


def groq_api_key_from_env() -> str | None:
    return os.getenv("GROQ_API_KEY") or None
