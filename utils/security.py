"""Credential encryption and log/message scrubbing."""
from __future__ import annotations

import os
import re
import stat

from cryptography.fernet import Fernet, InvalidToken

from utils.config import DATA_DIR
from utils.exceptions import QueryMateError

_KEY_FILE = DATA_DIR / "secret.key"


def _load_key() -> bytes:
    env = os.getenv("QUERYMATE_SECRET_KEY")
    if env:
        return env.encode()
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    try:
        os.chmod(_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return key


def encrypt_secret(plaintext: str) -> str:
    return Fernet(_load_key()).encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return Fernet(_load_key()).decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise QueryMateError(
            "Could not decrypt the saved password. The encryption key has changed; "
            "please re-save this connection."
        ) from e


_PATTERNS = [
    (re.compile(r"(mysql\+?\w*://[^:\s/]+:)[^@\s]+(@)", re.I), r"\1***\2"),
    (re.compile(r"(password\s*[=:]\s*)\S+", re.I), r"\1***"),
    (re.compile(r"(gsk_)[A-Za-z0-9]+"), r"\1***"),
]


def scrub(text: str, extra_secrets: tuple[str, ...] = ()) -> str:
    """Remove passwords / API keys / connection strings from an error message."""
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    for s in extra_secrets:
        if s:
            text = text.replace(s, "***")
    return text
