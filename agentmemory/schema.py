"""Strict v1 record contract validation and integrity helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime
from typing import Any, Mapping, Optional, Set
from posixpath import normpath

from .security import scan_for_secrets


SCHEMA_VERSION = 1

RECORD_TYPE_CHECKPOINT = "checkpoint"
RECORD_TYPE_CANDIDATE = "candidate"
RECORD_TYPE_PROJECT = "project_record"
RECORD_TYPE_VALUES = (RECORD_TYPE_CHECKPOINT, RECORD_TYPE_CANDIDATE, RECORD_TYPE_PROJECT)

KIND_CHECKPOINT = "checkpoint"
KIND_DECISION = "decision"
KIND_INCIDENT = "incident"
KIND_CONSTRAINT = "constraint"
KIND_VALUES = (KIND_CHECKPOINT, KIND_DECISION, KIND_INCIDENT, KIND_CONSTRAINT)

STATUS_CANDIDATE = "candidate"
STATUS_ACTIVE = "active"
STATUS_VALUES = (STATUS_CANDIDATE, STATUS_ACTIVE)

SEMANTIC_FACT = "fact"
SEMANTIC_INFERENCE = "inference"
SEMANTIC_INSTRUCTION = "instruction"
SEMANTIC_VALUES = (SEMANTIC_FACT, SEMANTIC_INFERENCE, SEMANTIC_INSTRUCTION)

SCOPE_LOCAL = "local"
SCOPE_PROJECT = "project"
SCOPE_VALUES = (SCOPE_LOCAL, SCOPE_PROJECT)

TOP_LEVEL_FIELDS = {
    "schema_version",
    "id",
    "record_type",
    "kind",
    "status",
    "semantic_role",
    "summary",
    "scope",
    "applies_to",
    "provenance",
    "content",
    "review",
    "created_at",
    "integrity",
}

APPLIES_FIELDS = {
    "repository_id",
    "worktree_id",
    "branch",
    "head",
    "paths",
}

PROVENANCE_FIELDS = {"source", "evidence_refs", "source_record_id"}
REVIEW_FIELDS = {"confirmed", "confirmed_by", "confirmed_at"}
INTEGRITY_FIELDS = {"version", "content_hash"}

MAX_SUMMARY_CHARS = 1024
MAX_CONTENT_BYTES = 16 * 1024
MAX_PATH_LENGTH = 2048
MAX_PATHS_COUNT = 32
MAX_RECORD_ID_LENGTH = 64
MAX_BRANCH_LENGTH = 255
MAX_PROVENANCE_SOURCE_LENGTH = 256
MAX_EVIDENCE_REF_LENGTH = 256
MAX_EVIDENCE_REFS = 32
MAX_SOURCE_RECORD_ID_LENGTH = 64
MAX_TIMESTAMP_LENGTH = 64

RUNTIME_VALIDATION_REQUIRED = [
    "canonical-json-shape",
    "canonical-json-utf8",
    "content-utf8-byte-limit",
    "timestamp-semantic-parse",
    "integrity_content_hash_verification",
    "secret_scan",
]

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RECORD_ID_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
RECORD_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ISO_TZ_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)$",
)
HEAD_SHA_RE = re.compile(r"^(?:[a-f0-9]{40}|UNBORN)$")
HEAD_SHA_ONLY_RE = re.compile(r"^[a-f0-9]{40}$")
SCHEMA_BRANCH_PATTERN = (
    r"^(?!DETACHED$)(?![./-])(?!.*/\.)(?!.*[./]$)(?!.*//)"
    r"(?!\.{1,2}(?:/|$))(?!.*/\.{1,2}(?:/|$))"
    r"(?![^/]*\.lock(?:/|$))(?!.*/[^/]*\.lock(?:/|$))"
    r"(?!.*\.\.)(?!.*@\{)(?!.*[\x00-\x20\x7f~^:?*\[\\]).+$"
)
SCHEMA_PATH_PATTERN = (
    r"^(?!\s)(?![^/]*:)(?!/)(?!.*\\)(?!.*//)(?!.*\x00)"
    r"(?!\.{1,2}(?:/|$))(?!.*/\.{1,2}(?:/|$))"
    r"(?!.*[/]$)(?!.*\s$).+$"
)
SCHEMA_BRANCH_RE = re.compile(SCHEMA_BRANCH_PATTERN)
SCHEMA_PATH_RE = re.compile(SCHEMA_PATH_PATTERN)


class RecordValidationError(ValueError):
    """Raised when a record fails the v1 contract."""


def _fail(message: str) -> None:
    raise RecordValidationError(message)


def _validate_json_shape(value: Any, seen: Optional[Set[int]] = None) -> None:
    if seen is None:
        seen = set()

    if value is None or isinstance(value, (str, int, bool)):
        return

    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("record is not valid canonical JSON")
        return

    if isinstance(value, list):
        value_id = id(value)
        if value_id in seen:
            _fail("record is not valid canonical JSON")
        seen.add(value_id)
        for item in value:
            _validate_json_shape(item, seen)
        seen.remove(value_id)
        return

    if isinstance(value, dict):
        value_id = id(value)
        if value_id in seen:
            _fail("record is not valid canonical JSON")
        seen.add(value_id)
        for key, item in value.items():
            if not isinstance(key, str):
                _fail("record is not valid canonical JSON")
            _validate_json_shape(item, seen)
        seen.remove(value_id)
        return

    _fail("record is not valid canonical JSON")


def canonical_json_dumps(value: Any) -> str:
    _validate_json_shape(value)
    try:
        rendered = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        rendered.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError) as exc:
        raise RecordValidationError("record is not valid canonical JSON") from exc
    return rendered


def compute_record_integrity(record: Mapping[str, Any]) -> str:
    """Return canonical integrity hash excluding `integrity.content_hash`."""

    _validate_json_shape(record)
    payload = copy.deepcopy(record)
    if not isinstance(payload, dict):
        _fail("record must be an object")

    integrity = payload.get("integrity")
    if not isinstance(integrity, dict):
        integrity = {}
    integrity = copy.deepcopy(integrity)
    integrity.pop("content_hash", None)
    payload["integrity"] = integrity

    digest = hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def annotate_with_integrity(record: Mapping[str, Any], version: int = 1) -> dict[str, Any]:
    """Return a copy of `record` with a computed canonical integrity hash."""

    if type(version) is not int or version <= 0:
        _fail("integrity.version must be a positive integer")

    _validate_json_shape(record)
    payload = copy.deepcopy(record)
    if not isinstance(payload, dict):
        _fail("record must be an object")

    payload["integrity"] = {"version": version}
    payload["integrity"]["content_hash"] = compute_record_integrity(payload)
    return payload


def _require_fields(value: Any, fields: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{context} must be an object")
    keys = set(value.keys())
    if keys != fields:
        _fail(f"{context} has unexpected fields")
    return value


def _require_str(value: Any, context: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail(f"{context} must be a string")
    if not allow_empty and not value.strip():
        _fail(f"{context} must be non-empty")
    return value


def _require_bool(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{context} must be a boolean")
    return value


def _validate_timestamp(value: Any, context: str) -> str:
    text = _require_str(value, context)
    if not ISO_TZ_RE.match(text):
        _fail(f"{context} must be timezone-aware ISO-8601")
    if len(text) > MAX_TIMESTAMP_LENGTH:
        _fail(f"{context} must be bounded")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        _fail(f"{context} must be valid ISO-8601 datetime")
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        _fail(f"{context} must be timezone-aware")
    return text


def _validate_paths(paths: Any) -> list[str]:
    if not isinstance(paths, list):
        _fail("applies_to.paths must be a list")
    if len(paths) > MAX_PATHS_COUNT:
        _fail("applies_to.paths must be bounded")
    cleaned: list[str] = []
    for path in paths:
        if not isinstance(path, str):
            _fail("applies_to.paths entries must be strings")
        if len(path) > MAX_PATH_LENGTH:
            _fail("applies_to.paths entries must be bounded")
        if not SCHEMA_PATH_RE.fullmatch(path):
            _fail("applies_to.paths entries must be canonical repository-relative POSIX paths")
        normalized = path
        if normalized != normpath(normalized):
            _fail("applies_to.paths entries must be canonical posix paths")
        segments = normalized.split("/")
        if "." in segments or ".." in segments:
            _fail("applies_to.paths entries must not contain dot segments")
        cleaned.append(normalized)
    return cleaned


def _validate_head(value: Any) -> str:
    text = _require_str(value, "applies_to.head")
    if not HEAD_SHA_RE.match(text):
        _fail("applies_to.head must be a lower-case 40-hex commit SHA or UNBORN")
    return text


def _validate_branch(value: Any) -> str:
    branch = _require_str(value, "applies_to.branch")
    if branch == "DETACHED":
        return branch
    if len(branch) > MAX_BRANCH_LENGTH:
        _fail("applies_to.branch must be bounded")
    if not SCHEMA_BRANCH_RE.fullmatch(branch):
        _fail("applies_to.branch has invalid syntax")
    return branch


def _validate_record_identity(value: Any, context: str, *, lower_hex: bool = False) -> str:
    value = _require_str(value, f"applies_to.{context}")
    if lower_hex:
        if not RECORD_ID_SHA256_RE.match(value):
            _fail(f"applies_to.{context} must be lower-case SHA256 hex")
        return value
    if not RECORD_ID_RE.match(value):
        _fail(f"applies_to.{context} has invalid syntax")
    if len(value) > MAX_RECORD_ID_LENGTH:
        _fail(f"applies_to.{context} must be no longer than {MAX_RECORD_ID_LENGTH} characters")
    return value


def _validate_applies_to(value: Any) -> dict[str, Any]:
    applies = _require_fields(value, APPLIES_FIELDS, "applies_to")
    applies["repository_id"] = _validate_record_identity(
        applies["repository_id"],
        "repository_id",
        lower_hex=True,
    )
    applies["worktree_id"] = _validate_record_identity(
        applies["worktree_id"],
        "worktree_id",
        lower_hex=True,
    )
    applies["branch"] = _validate_branch(applies["branch"])
    applies["head"] = _validate_head(applies["head"])
    applies["paths"] = _validate_paths(applies["paths"])
    return applies


def _validate_provenance(value: Any) -> dict[str, Any]:
    provenance = _require_fields(value, PROVENANCE_FIELDS, "provenance")
    provenance["source"] = _require_str(provenance["source"], "provenance.source")
    if len(provenance["source"]) > MAX_PROVENANCE_SOURCE_LENGTH:
        _fail("provenance.source must be bounded")
    evidence_refs = provenance["evidence_refs"]
    if not isinstance(evidence_refs, list):
        _fail("provenance.evidence_refs must be a list")
    if len(evidence_refs) > MAX_EVIDENCE_REFS:
        _fail("provenance.evidence_refs must be bounded")
    for index, reference in enumerate(evidence_refs):
        if not isinstance(reference, str) or not reference.strip():
            _fail(f"provenance.evidence_refs[{index}] must be a non-empty string")
        if len(reference) > MAX_EVIDENCE_REF_LENGTH:
            _fail(f"provenance.evidence_refs[{index}] must be bounded")
    provenance["evidence_refs"] = [str(reference) for reference in evidence_refs]
    provenance["source_record_id"] = _require_str(
        provenance["source_record_id"],
        "provenance.source_record_id",
        allow_empty=False,
    )
    if len(provenance["source_record_id"]) > MAX_SOURCE_RECORD_ID_LENGTH:
        _fail("provenance.source_record_id must be bounded")
    return provenance


def _validate_review(value: Any) -> dict[str, Any]:
    review = _require_fields(value, REVIEW_FIELDS, "review")
    review["confirmed"] = _require_bool(review["confirmed"], "review.confirmed")
    confirmed_by = review["confirmed_by"]
    confirmed_at = review["confirmed_at"]

    if not review["confirmed"]:
        if confirmed_by is not None:
            _fail("review.confirmed_by must be null when review is not confirmed")
        if confirmed_at is not None:
            _fail("review.confirmed_at must be null when review is not confirmed")
        review["confirmed_by"] = None
        review["confirmed_at"] = None
        return review

    review["confirmed_by"] = _require_str(
        confirmed_by,
        "review.confirmed_by",
        allow_empty=False,
    )
    review["confirmed_at"] = _validate_timestamp(
        confirmed_at,
        "review.confirmed_at",
    )
    return review


def _validate_content(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("content must be a JSON object")
    _validate_json_shape(value)
    content_bytes = canonical_json_dumps(value).encode("utf-8")
    if len(content_bytes) > MAX_CONTENT_BYTES:
        _fail("content must be size bounded")
    return value


def _validate_integrity(value: Any) -> dict[str, Any]:
    integrity = _require_fields(value, INTEGRITY_FIELDS, "integrity")
    version = integrity["version"]
    if type(version) is not int or version <= 0:
        _fail("integrity.version must be a positive integer")
    content_hash = _require_str(integrity["content_hash"], "integrity.content_hash")
    if not SHA256_RE.match(content_hash):
        _fail("integrity.content_hash must be sha256 hex digest")
    return integrity


def _validate_record_id(record_id: Any) -> str:
    value = _require_str(record_id, "id")
    if not RECORD_ID_RE.match(value):
        _fail("id has invalid syntax")
    if len(value) > MAX_RECORD_ID_LENGTH:
        _fail("id is too long")
    return value


def validate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate all v1 contract rules and integrity."""

    _validate_json_shape(record)
    record_obj = _require_fields(copy.deepcopy(record), TOP_LEVEL_FIELDS, "record")

    if type(record_obj.get("schema_version")) is not int:
        _fail("schema_version must be an integer")
    if record_obj["schema_version"] != SCHEMA_VERSION:
        _fail("unknown schema_version")

    record_obj["id"] = _validate_record_id(record_obj["id"])
    record_type = _require_str(record_obj["record_type"], "record_type")
    if record_type not in RECORD_TYPE_VALUES:
        _fail("record_type has invalid value")

    kind = _require_str(record_obj["kind"], "kind")
    if kind not in KIND_VALUES:
        _fail("kind has invalid value")

    status = _require_str(record_obj["status"], "status")
    if status not in STATUS_VALUES:
        _fail("status has invalid value")

    semantic_role = _require_str(record_obj["semantic_role"], "semantic_role")
    if semantic_role not in SEMANTIC_VALUES:
        _fail("semantic_role has invalid value")

    scope = _require_str(record_obj["scope"], "scope")
    if scope not in SCOPE_VALUES:
        _fail("scope has invalid value")

    summary = _require_str(record_obj["summary"], "summary")
    if not summary.strip() or len(summary) > MAX_SUMMARY_CHARS:
        _fail("summary must be non-empty and bounded")
    record_obj["summary"] = summary

    record_obj["applies_to"] = _validate_applies_to(record_obj["applies_to"])
    record_obj["provenance"] = _validate_provenance(record_obj["provenance"])
    record_obj["content"] = _validate_content(record_obj["content"])
    record_obj["review"] = _validate_review(record_obj["review"])
    record_obj["created_at"] = _validate_timestamp(record_obj["created_at"], "created_at")
    record_obj["integrity"] = _validate_integrity(record_obj["integrity"])

    scan_payload = copy.deepcopy(record_obj)
    scan_payload["integrity"] = copy.deepcopy(scan_payload["integrity"])
    scan_payload["integrity"].pop("content_hash", None)
    scan_for_secrets(scan_payload)

    if record_type == RECORD_TYPE_CHECKPOINT:
        if kind != KIND_CHECKPOINT:
            _fail("checkpoint requires kind checkpoint")
        if status != STATUS_ACTIVE:
            _fail("checkpoint requires active status")
        if scope != SCOPE_LOCAL:
            _fail("checkpoint requires local scope")
        if semantic_role != SEMANTIC_FACT:
            _fail("checkpoint requires fact semantic role")
        if record_obj["review"]["confirmed"]:
            _fail("checkpoint must be unconfirmed")
        if record_obj["review"]["confirmed_by"] is not None:
            _fail("checkpoint must not have confirmed_by when unconfirmed")
        if record_obj["review"]["confirmed_at"] is not None:
            _fail("checkpoint must not have confirmed_at when unconfirmed")
        if not isinstance(record_obj["applies_to"]["head"], str):
            _fail("checkpoint requires head")
        if not record_obj["applies_to"]["head"]:
            _fail("checkpoint requires head")

    elif record_type == RECORD_TYPE_CANDIDATE:
        if kind not in (KIND_DECISION, KIND_INCIDENT, KIND_CONSTRAINT):
            _fail("candidate requires decision, incident or constraint kind")
        if status != STATUS_CANDIDATE:
            _fail("candidate requires candidate status")
        if scope != SCOPE_LOCAL:
            _fail("candidate requires local scope")
        if semantic_role not in (SEMANTIC_FACT, SEMANTIC_INFERENCE):
            _fail("candidate prohibits instruction role")
        if record_obj["review"]["confirmed"]:
            _fail("candidate must not be confirmed")
        if record_obj["review"]["confirmed_by"] is not None:
            _fail("candidate must not have confirmed_by when unconfirmed")
        if record_obj["review"]["confirmed_at"] is not None:
            _fail("candidate must not have confirmed_at when unconfirmed")

    else:
        if kind not in (KIND_DECISION, KIND_INCIDENT, KIND_CONSTRAINT):
            _fail("project_record requires decision, incident or constraint kind")
        if status != STATUS_ACTIVE:
            _fail("project_record requires active status")
        if scope != SCOPE_PROJECT:
            _fail("project_record requires project scope")
        if semantic_role == SEMANTIC_INSTRUCTION and kind != KIND_CONSTRAINT:
            _fail("instruction semantic role is only valid for project constraints")
        if not record_obj["review"]["confirmed"]:
            _fail("project_record must be confirmed")
        if record_obj["review"]["confirmed_by"] != "explicit_user":
            _fail("project_record review requires explicit_user confirmation")
        if record_obj["review"]["confirmed_at"] is None:
            _fail("project_record review requires confirmed_at")
        if not record_obj["provenance"]["source_record_id"]:
            _fail("provenance.source_record_id must be non-empty for project_record")

    expected_hash = compute_record_integrity(record_obj)
    if record_obj["integrity"]["content_hash"] != expected_hash:
        _fail("integrity.content_hash mismatch")

    return record_obj
