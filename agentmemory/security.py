"""Security primitives for secret detection in AgentMemory records."""

from __future__ import annotations

import re
from typing import Any


SECRET_SCAN_ERROR = "record contains disallowed secret material"


class SecretScanError(ValueError):
    """Raised when record data contains disallowed secret-like material."""


_RE_KEY = re.compile(r"^(authorization|auth|api[_-]?key|access[_-]?key|secret|secret[_-]?key|password|passwd|token|cookie|session|client[_-]?secret)$", re.IGNORECASE)
_RE_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE)
_RE_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9\-_\.~\+/=]{20,}\b")
_RE_OPENAI = re.compile(
    r"(?<![A-Za-z0-9_])sk-(?:[A-Za-z0-9]{20,}|(?:proj|svcacct)-[A-Za-z0-9_-]{20,}|ant-(?:api|oat)\d{2}-[A-Za-z0-9_-]{20,})(?![A-Za-z0-9_])"
)
_RE_AWS = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_RE_GITHUB = re.compile(
    r"(?<![A-Za-z0-9_])(?:gh[opurs]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,})(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_RE_DB_CONN = re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb|redis|amqp|rabbitmq|mssql)://[^/\s@]+:[^/\s@]+@", re.IGNORECASE)


def _contains_secret_text(value: str) -> bool:
    for pattern in (
        _RE_PRIVATE_KEY,
        _RE_BEARER,
        _RE_OPENAI,
        _RE_AWS,
        _RE_GITHUB,
        _RE_DB_CONN,
    ):
        if pattern.search(value):
            return True
    return False


def _contains_secret_key_name(key: str, value: Any) -> bool:
    if not _RE_KEY.match(str(key).strip()):
        return False
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (int, float, bool)):
        return False
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def scan_for_secrets(value: Any) -> None:
    """Scan nested mappings and sequences for credential-like values."""

    if isinstance(value, str):
        if _contains_secret_text(value):
            raise SecretScanError(SECRET_SCAN_ERROR)
        return
    if isinstance(value, bytes):
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str):
                if _contains_secret_text(key):
                    raise SecretScanError(SECRET_SCAN_ERROR)
            else:
                _ = str(key)
            if _contains_secret_key_name(key, nested):
                raise SecretScanError(SECRET_SCAN_ERROR)
            scan_for_secrets(nested)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            scan_for_secrets(item)
        return
    if isinstance(value, (int, float, bool, type(None))):
        return
    if isinstance(value, object):
        text = str(value)
        if _contains_secret_text(text):
            raise SecretScanError(SECRET_SCAN_ERROR)
