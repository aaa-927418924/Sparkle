"""Input validation shared by the local and future remote MCP transports."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterator


MAX_LIMIT = 50
MAX_QUERY_LENGTH = 200
MAX_TAGS = 20
MAX_TAG_LENGTH = 80
MAX_CURSOR_LENGTH = 2048
MAX_ID = 2**63 - 1


class McpInputError(ValueError):
    """A validation error that can be returned without leaking implementation data."""

    def __init__(self, message: str, *, field: str | None = None, code: str = "invalid_input"):
        super().__init__(message)
        self.message = message
        self.field = field
        self.code = code


def optional_text(value: str | None, *, field: str, max_length: int) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > max_length:
        raise McpInputError(f"{field} is too long.", field=field, code="input_too_long")
    return value


def required_text(value: str, *, field: str, max_length: int) -> str:
    normalized = optional_text(value, field=field, max_length=max_length)
    if normalized is None:
        raise McpInputError(f"{field} is required.", field=field)
    return normalized


def normalized_tags(values: list[str] | None) -> list[str]:
    if not values:
        return []
    if len(values) > MAX_TAGS:
        raise McpInputError(f"tags accepts at most {MAX_TAGS} values.", field="tags")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = required_text(value, field="tags", max_length=MAX_TAG_LENGTH)
        key = tag.casefold()
        if key not in seen:
            result.append(tag)
            seen.add(key)
    return result


def valid_id(value: int, *, field: str = "id") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > MAX_ID:
        raise McpInputError(f"{field} must be a positive integer.", field=field)
    return value


def valid_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > MAX_LIMIT:
        raise McpInputError(f"limit must be between 1 and {MAX_LIMIT}.", field="limit")
    return value


def valid_cursor(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_CURSOR_LENGTH:
        raise McpInputError("cursor is too long.", field="cursor", code="input_too_long")
    return value


def normalized_date(value: str | None, *, field: str, end_of_day: bool = False) -> str | None:
    value = optional_text(value, field=field, max_length=40)
    if value is None:
        return None
    try:
        if len(value) == 10:
            parsed = date.fromisoformat(value)
            return f"{parsed.isoformat()} {'23:59:59' if end_of_day else '00:00:00'}"
        parsed_datetime = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise McpInputError(f"{field} must be an ISO date or datetime.", field=field) from exc
    if parsed_datetime.tzinfo is not None:
        parsed_datetime = parsed_datetime.replace(tzinfo=None)
    return parsed_datetime.isoformat(sep=" ")


@contextmanager
def normalized_date_range(
    date_from: str | None,
    date_to: str | None,
) -> Iterator[tuple[str | None, str | None]]:
    start = normalized_date(date_from, field="date_from")
    end = normalized_date(date_to, field="date_to", end_of_day=True)
    if start and end and start > end:
        raise McpInputError("date_from must not be later than date_to.", field="date_from")
    yield start, end
