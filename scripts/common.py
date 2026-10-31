"""Shared streaming I/O; never log ticket text or private identifiers."""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from typing import Iterator


class InputError(ValueError):
    """An input error safe to display without exposing private records."""


def resolve_data_dir(value: str | None = None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    try:
        from app.config import get_data_dir
        return Path(get_data_dir())
    except ImportError:
        return Path(os.environ.get("SUPPORT_DATA_DIR", "data")).expanduser().resolve()


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                # A blank line is not a ticket; skip it consistently in both tools.
                continue
            try:
                row = json.loads(line)
            except (ValueError, TypeError) as exc:
                raise InputError(f"Некорректный JSON в строке {line_number}.") from exc
            if not isinstance(row, dict):
                raise InputError(f"В строке {line_number} ожидается JSON-объект.")
            yield line_number, row


def validate_result(result: dict, taxonomy: dict, kind: str, citations: set[tuple[str, str, str]]) -> list[str]:
    """Check the public contract, taxonomy membership, and exact citation identity.

    These are mechanical checks, not semantic ground truth or accuracy.
    A rule number alone is insufficient: numbers repeat between rule sections.
    """
    errors: list[str] = []
    expected = {"lang", "category", "priority", "is_spam_or_duplicate", "extracted", "draft_reply", "needs_human", "confidence", "reasons"}
    if not isinstance(result, dict) or set(result) != expected:
        return ["response_keys"]
    categories = {c["code"] for c in taxonomy["categories"] if c["kind"] == kind}
    priorities = {p["code"] for p in taxonomy["priorities"]}
    if result["category"] not in categories:
        errors.append("category_kind")
    if result["priority"] not in priorities:
        errors.append("priority")
    if not isinstance(result["lang"], str) or not result["lang"]:
        errors.append("language")
    if type(result["needs_human"]) is not bool or type(result["is_spam_or_duplicate"]) is not bool:
        errors.append("boolean_fields")
    if type(result["confidence"]) not in (float, int) or not 0 <= result["confidence"] <= 1:
        errors.append("confidence")
    if not isinstance(result["reasons"], list) or not all(isinstance(x, str) and x for x in result["reasons"]):
        errors.append("reasons")
    ex = result["extracted"]
    if not isinstance(ex, dict) or set(ex) != {"nickname", "rule_refs", "has_evidence", "server"}:
        errors.append("extracted_keys")
        ex = {}
    else:
        if not all(ex[k] is None or isinstance(ex[k], str) for k in ("nickname", "server")):
            errors.append("extracted_strings")
        if type(ex["has_evidence"]) is not bool:
            errors.append("has_evidence")
        if not isinstance(ex["rule_refs"], list) or not all(isinstance(x, str) for x in ex["rule_refs"]):
            errors.append("rule_refs")
    draft = result["draft_reply"]
    if not isinstance(draft, dict) or set(draft) != {"lang", "text", "cited"}:
        errors.append("draft_keys")
        return errors
    if draft["lang"] != result["lang"] and not (result["lang"] == "lat" and draft["lang"] == "und"):
        errors.append("draft_language")
    if not isinstance(draft["text"], str) or not draft["text"].strip():
        errors.append("draft_text")
    if not isinstance(draft["cited"], list):
        errors.append("cited_type")
        return errors
    cited_refs = []
    for citation in draft["cited"]:
        if not isinstance(citation, dict):
            errors.append("citation_shape")
            continue
        identity = (citation.get("section"), citation.get("ref"), citation.get("text"))
        if identity not in citations:
            errors.append("citation_not_exact_source")
        cited_refs.append(citation.get("ref"))
    if isinstance(ex.get("rule_refs"), list) and set(ex["rule_refs"]) != set(cited_refs):
        errors.append("citation_refs_mismatch")
    return errors
