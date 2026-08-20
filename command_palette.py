"""Unified local search and optional natural-language query parsing.

The command palette deliberately keeps the language model out of the data
retrieval path.  The model, when available, turns a Japanese query into a
small validated filter object; SQLite remains responsible for reading and
ranking Sparkle's data.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import threading
import traceback
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from paths import get_app_data_dir


MODEL_ID = "LiquidAI/LFM2.5-350M"
MODEL_DIRECTORY_NAME = "LFM2.5-350M"
ENTITY_TYPES = ("clip", "note", "task", "project")
MAX_QUERY_LENGTH = 400
DEFAULT_LIMIT = 20


class CommandPaletteSearchRequest(BaseModel):
    query: str = Field(default="", max_length=MAX_QUERY_LENGTH)
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=50)
    entity_types: Optional[list[str]] = None
    use_ai: bool = True


class SearchIntent(BaseModel):
    entity_types: list[str] = Field(default_factory=lambda: list(ENTITY_TYPES))
    text_query: str = ""
    is_done: Optional[bool] = None
    is_favorite: Optional[bool] = None
    due_from: Optional[str] = None
    due_to: Optional[str] = None
    project_name: Optional[str] = None
    category: Optional[str] = None
    tag: Optional[str] = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=50)


class CommandPaletteResultOut(BaseModel):
    entity_type: str
    id: int
    title: str
    snippet: Optional[str] = None
    target: str
    is_done: Optional[bool] = None
    is_favorite: Optional[bool] = None
    due_date: Optional[str] = None
    priority: Optional[int] = None
    score: Optional[float] = None


class CommandPaletteSearchOut(BaseModel):
    query: str
    parser: str
    search_mode: str
    intent: SearchIntent
    total: int
    results: list[CommandPaletteResultOut]
    device: Optional[str] = None


class CommandPaletteStatusOut(BaseModel):
    model_id: str
    backend: str
    configured: bool
    available: bool
    device: Optional[str] = None
    model_loaded: bool = False
    message: str
    embedding_available: bool = False
    embedding_device: Optional[str] = None
    embedding_model_loaded: bool = False


SEARCH_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS search_documents (
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    is_done INTEGER,
    is_favorite INTEGER,
    due_date TEXT,
    priority INTEGER,
    created_at TEXT,
    updated_at TEXT,
    project_id INTEGER,
    PRIMARY KEY (entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS search_index_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO search_index_meta(key, value) VALUES ('dirty', '1');
INSERT OR IGNORE INTO search_index_meta(key, value) VALUES ('fts_available', '0');
"""


_SEARCH_SOURCE_TABLES = (
    "clips",
    "tasks",
    "notes",
    "projects",
    "categories",
    "tags",
    "clip_tags",
    "project_clips",
    "project_notes",
    "task_notes",
)


def _trigger_sql() -> str:
    statements: list[str] = []
    for table in _SEARCH_SOURCE_TABLES:
        for event in ("INSERT", "UPDATE", "DELETE"):
            trigger_name = f"search_dirty_{table}_{event.lower()}"
            statements.append(
                f"""
CREATE TRIGGER IF NOT EXISTS {trigger_name}
AFTER {event} ON {table}
BEGIN
    INSERT OR REPLACE INTO search_index_meta(key, value) VALUES ('dirty', '1');
END;
"""
            )
    return "\n".join(statements)


def ensure_search_schema(conn: sqlite3.Connection) -> bool:
    """Create the local search metadata and return whether FTS5 is usable."""
    conn.executescript(SEARCH_SCHEMA_SQL)

    fts_available = False
    existing = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'search_documents_fts'"
    ).fetchone()
    if existing:
        fts_available = True
    else:
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS search_documents_fts
                USING fts5(
                    entity_type UNINDEXED,
                    entity_id UNINDEXED,
                    title,
                    content,
                    tokenize = 'trigram'
                )
                """
            )
            fts_available = True
        except sqlite3.OperationalError:
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS search_documents_fts
                    USING fts5(entity_type UNINDEXED, entity_id UNINDEXED, title, content)
                    """
                )
                fts_available = True
            except sqlite3.OperationalError:
                fts_available = False

    conn.executescript(_trigger_sql())
    conn.execute(
        "INSERT OR REPLACE INTO search_index_meta(key, value) VALUES ('fts_available', ?)",
        ("1" if fts_available else "0",),
    )
    return fts_available


def _text(*parts: Any) -> str:
    return " ".join(str(part).strip() for part in parts if part is not None and str(part).strip())


def _local_date() -> date:
    try:
        return datetime.now(ZoneInfo("Asia/Tokyo")).date()
    except Exception:
        return datetime.now().astimezone().date()


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip().casefold()


# The 350M model is reliable at picking entity types and free text but tends to
# fabricate "false" for absent filters on plain title searches, which would hide
# every row that does not carry the flag (e.g. is_done is NULL on clips).  These
# triggers make boolean/date filters from the model conditional on the raw query
# actually mentioning the corresponding concern, mirroring the heuristic.
_DONE_TRIGGER = re.compile(
    r"(?:未完了|進行中|未実施|未着手|残(?:り|っている)|完了済み|完了した|終わった|完了|"
    r"done|completed|pending|incomplete|todo|open)",
    re.IGNORECASE,
)
_FAVORITE_TRIGGER = re.compile(
    r"(?:お気に入り|favorite|favourites?|star(?:red)?|ブックマーク)",
    re.IGNORECASE,
)
_DUE_TRIGGER = re.compile(
    r"(?:今日|本日|明日|明後日|きょう|あした|今週|来週|先週|today|tomorrow|"
    r"this week|next week|last week|overdue|期限切れ|期限超過|期限が過ぎた)",
    re.IGNORECASE,
)

# Queries are broken into Latin words and Japanese segments separated by
# particles.  The Latin words are treated as strong anchors (AND across them,
# with synonym expansion); the Japanese segments only boost ranking when Latin
# anchors exist, so grammar such as "で使えそうな" never hides results.
_ENGLISH_STOPWORDS = frozenset(
    "a an the of for and or to in on at by with as is are was were be do does did "
    "from into that this these those it its you your we our they their i he she them "
    "me my not no so but if then than too very just also can will would should could "
    "may might must about after before between during without within under over out "
    "up down off".split()
)
_JAPANESE_NOISE = frozenset(
    "よう もの こと ため とき 中 的 な ん みたい すぎ たち くらい ぐらい など から まで".split()
)
_ASCII_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")
_PARTICLE_SPLIT_RE = re.compile(r"(?:で|に|の|な|を|へ|と|や|から|まで|など|って|とか)")

# Deterministic synonym expansion.  The palette data stores labels like
# "AMVで使えそう" and tags like "曲" rather than the literal word "BGM", so
# exact substring matching alone returns nothing for natural queries.  Each
# group is symmetric: every member maps to the whole group.
_SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"bgm", "曲", "音楽", "楽曲", "サウンド", "ミュージック", "音源", "music", "歌"}),
    frozenset({"amv", "edit", "edits", "編集", "エディット", "動画編集", "映像編集", "gmv"}),
    frozenset({"動画", "映像", "video", "videos", "ビデオ", "movie"}),
    frozenset({"クリップ", "clip", "clips", "資料", "リンク", "ブックマーク"}),
    frozenset({"メモ", "ノート", "note", "notes"}),
    frozenset({"タスク", "task", "tasks", "todo", "作業", "やること"}),
    frozenset({"プロジェクト", "project", "projects"}),
)
_TERM_SYNONYMS: dict[str, frozenset[str]] = {
    member: group
    for group in _SYNONYM_GROUPS
    for member in group
}


def _term_variants(term: str) -> list[str]:
    variants = _TERM_SYNONYMS.get(term, ())
    return sorted({term, *variants})


def _query_slots(text_query: str) -> tuple[list[str], list[str]]:
    """Return (required terms, optional Japanese boost terms)."""
    normalized = _normalize(text_query)
    if not normalized:
        return [], []
    ascii_words = [
        word
        for word in _ASCII_WORD_RE.findall(normalized)
        if len(word) >= 2 and word not in _ENGLISH_STOPWORDS
    ]
    segments: list[str] = []
    for segment in _PARTICLE_SPLIT_RE.split(normalized):
        if not segment:
            continue
        segments.extend(part for part in re.split(r"\s+", segment) if part)
    japanese = [segment for segment in segments if not segment.isascii()]

    def strong(segment: str) -> bool:
        return len(segment) >= 2 and segment not in _JAPANESE_NOISE

    if ascii_words:
        required = list(dict.fromkeys(ascii_words))
        optional = list(
            dict.fromkeys(
                segment for segment in japanese if strong(segment) and segment not in required
            )
        )
        return required, optional
    strong_segments = [segment for segment in japanese if strong(segment)]
    if strong_segments:
        return list(dict.fromkeys(strong_segments)), []
    return [normalized], []


def _heuristic_intent(query: str) -> SearchIntent:
    raw = unicodedata.normalize("NFKC", (query or "")[:MAX_QUERY_LENGTH]).strip()
    normalized = _normalize(raw)
    entity_types: list[str] = []
    entity_patterns = {
        "clip": r"(?:クリップ|clip|clips|資料|リンク|ブックマーク)",
        "note": r"(?:メモ|ノート|note|notes)",
        "task": r"(?:タスク|todo|to-do|やること|作業)",
        "project": r"(?:プロジェクト|project|projects)",
    }
    for entity_type, pattern in entity_patterns.items():
        if re.search(pattern, normalized, re.IGNORECASE):
            entity_types.append(entity_type)

    is_done: Optional[bool] = None
    if re.search(r"(?:未完了|進行中|未実施|残っている|incomplete|todo)", normalized):
        is_done = False
    elif re.search(r"(?:完了済み|完了した|終わった|done|completed)", normalized):
        is_done = True

    if re.search(r"(?:お気に入りではない|お気に入りでない|お気に入りじゃない|非お気に入り|not favorite)", normalized):
        is_favorite: Optional[bool] = False
    else:
        is_favorite = bool(re.search(r"(?:お気に入り|favorite|favourites?)", normalized)) or None

    today = _local_date()
    due_from: Optional[str] = None
    due_to: Optional[str] = None
    if re.search(r"(?:今日|本日|today)", normalized):
        due_from = due_to = today.isoformat()
    elif re.search(r"(?:明日|tomorrow)", normalized):
        tomorrow = today + timedelta(days=1)
        due_from = due_to = tomorrow.isoformat()
    elif re.search(r"(?:今週|this week)", normalized):
        due_from = (today - timedelta(days=today.weekday())).isoformat()
        due_to = (today + timedelta(days=6 - today.weekday())).isoformat()
    elif re.search(r"(?:来週|next week)", normalized):
        next_monday = today + timedelta(days=7 - today.weekday())
        due_from = next_monday.isoformat()
        due_to = (next_monday + timedelta(days=6)).isoformat()
    elif re.search(r"(?:期限切れ|期限超過|期限が過ぎた|overdue)", normalized):
        due_to = (today - timedelta(days=1)).isoformat()

    removable = [
        *entity_patterns.values(),
        r"未完了|進行中|未実施|残っている|incomplete|todo",
        r"完了済み|完了した|終わった|done|completed",
        r"お気に入りではない|お気に入りでない|お気に入りじゃない|非お気に入り|not favorite",
        r"お気に入り|favorite|favourites?",
        r"今日|本日|today|明日|tomorrow|今週|this week|来週|next week",
        r"期限切れ|期限超過|期限が過ぎた|overdue",
        r"すべて|全部|一覧|見せて|表示して|表示|教えて|検索して|探して|検索|search",
        r"(?:^|\s)(?:の|を|が|は|に|で|へ|と|だけ|のみ)(?=\s|$)",
    ]
    text_query = raw
    for pattern in removable:
        text_query = re.sub(pattern, " ", text_query, flags=re.IGNORECASE)
    text_query = re.sub(r"[「」『』（）()：:、,]", " ", text_query)
    text_query = re.sub(r"\s+", " ", text_query).strip()

    return SearchIntent(
        entity_types=entity_types or list(ENTITY_TYPES),
        text_query=text_query,
        is_done=is_done,
        is_favorite=is_favorite,
        due_from=due_from,
        due_to=due_to,
    )


def _configured_model_source() -> Optional[str]:
    configured = os.getenv("SPARKLE_LLM_MODEL_PATH", "").strip()
    if configured:
        return configured
    default_path = get_app_data_dir() / "models" / MODEL_DIRECTORY_NAME
    if default_path.exists():
        return str(default_path)
    return None


def _resolve_model_files(source: str) -> tuple[Path, Optional[str]]:
    """Return the model directory and an optional GGUF filename."""
    path = Path(source).expanduser()
    if path.is_file():
        return path.parent, path.name if path.suffix.casefold() == ".gguf" else None
    if not path.is_dir():
        return path, None

    gguf_files = sorted(
        path.glob("*.gguf"),
        key=lambda item: (
            "q6_k" not in item.name.casefold(),
            item.name.casefold(),
        ),
    )
    return path, gguf_files[0].name if gguf_files else None


def _model_payload_to_intent(payload: Any) -> Optional[SearchIntent]:
    if not isinstance(payload, dict):
        return None

    aliases = {
        "clip": "clip",
        "clips": "clip",
        "note": "note",
        "notes": "note",
        "memo": "note",
        "memos": "note",
        "task": "task",
        "tasks": "task",
        "todo": "task",
        "todos": "task",
        "project": "project",
        "projects": "project",
    }
    raw_entities = payload.get("entity_types")
    if isinstance(raw_entities, str):
        raw_entities = [raw_entities]
    entities: list[str] = []
    if isinstance(raw_entities, list):
        for item in raw_entities:
            mapped = aliases.get(_normalize(str(item)))
            if mapped and mapped not in entities:
                entities.append(mapped)

    def optional_text(key: str) -> Optional[str]:
        value = payload.get(key)
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def optional_bool(key: str) -> Optional[bool]:
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"true", "yes", "1"}:
                return True
            if normalized in {"false", "no", "0"}:
                return False
        return None

    try:
        limit = max(1, min(int(payload.get("limit", DEFAULT_LIMIT)), 50))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT

    return SearchIntent(
        entity_types=entities or list(ENTITY_TYPES),
        text_query=str(payload.get("text_query") or "").strip(),
        is_done=optional_bool("is_done"),
        is_favorite=optional_bool("is_favorite"),
        due_from=optional_text("due_from"),
        due_to=optional_text("due_to"),
        project_name=optional_text("project_name"),
        category=optional_text("category"),
        tag=optional_text("tag"),
        limit=limit,
    )


class _LocalIntentParser:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._device = None
        self._attempted = False
        self._last_error_type: Optional[str] = None

    def parse(self, query: str) -> Optional[SearchIntent]:
        if not self._load():
            return None
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are Sparkle's Japanese search parser. "
                        "Return exactly one compact JSON object without Markdown. "
                        "Never answer the user and never write SQL. Always include every key. "
                        "entity_types must contain only singular values from "
                        "[\"clip\",\"note\",\"task\",\"project\"]. "
                        "Use null for absent filters and an integer from 1 to 50 for limit. "
                        "If the query is a plain title or keyword search without an explicit "
                        "status, favorite, or date request, is_done, is_favorite, due_from, "
                        "and due_to MUST be null. Never default is_done or is_favorite to "
                        "false unless the query explicitly asks for incomplete items or "
                        "non-favorites. "
                        "Schema keys: entity_types, text_query, is_done, is_favorite, "
                        "due_from, due_to, project_name, category, tag, limit. "
                        "Example for 未完了タスク: "
                        "{\"entity_types\":[\"task\"],\"text_query\":\"\","
                        "\"is_done\":false,\"is_favorite\":null,\"due_from\":null,"
                        "\"due_to\":null,\"project_name\":null,\"category\":null,"
                        "\"tag\":null,\"limit\":20}."
                    ),
                },
                {"role": "user", "content": query[:MAX_QUERY_LENGTH]},
            ]
            model_inputs = self._tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
            )
            model_inputs = {
                key: value.to(self._device) if hasattr(value, "to") else value
                for key, value in model_inputs.items()
            }
            input_length = model_inputs["input_ids"].shape[-1]
            with self._torch.inference_mode():
                output = self._model.generate(
                    **model_inputs,
                    max_new_tokens=256,
                    do_sample=False,
                    repetition_penalty=1.05,
                    pad_token_id=self._tokenizer.eos_token_id,
                )
            generated = output[0][input_length:]
            text = self._tokenizer.decode(generated, skip_special_tokens=True).strip()
            start = text.find("{")
            if start < 0:
                return None
            payload, _ = json.JSONDecoder().raw_decode(text[start:])
            return _model_payload_to_intent(payload)
        except Exception:
            return None

    def _load(self) -> bool:
        if self._model is not None:
            return True
        if self._attempted:
            return False
        with self._lock:
            if self._model is not None:
                return True
            if self._attempted:
                return False
            self._attempted = True
            source = _configured_model_source()
            if (
                not source
                or importlib.util.find_spec("transformers") is None
                or importlib.util.find_spec("torch") is None
            ):
                return False
            try:
                import torch
                import gguf

                # PyInstaller can preserve gguf's distribution metadata while
                # omitting the package-to-distribution mapping used by
                # Transformers. Restore the version on the imported module so
                # Transformers' GGUF capability check does not parse "N/A".
                if not getattr(gguf, "__version__", None):
                    try:
                        from importlib.metadata import version as distribution_version

                        gguf.__version__ = distribution_version("gguf")
                    except Exception:
                        gguf.__version__ = "0.19.0"

                from transformers import AutoModelForCausalLM, AutoTokenizer

                self._torch = torch
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
                model_dir, gguf_file = _resolve_model_files(source)
                self._tokenizer = AutoTokenizer.from_pretrained(
                    str(model_dir),
                    local_files_only=True,
                )
                model_kwargs: dict[str, Any] = {"local_files_only": True}
                if gguf_file:
                    model_kwargs["gguf_file"] = gguf_file
                    model_kwargs["dtype"] = (
                        torch.float16 if self._device == "cuda" else torch.float32
                    )
                elif self._device == "cuda":
                    model_kwargs["dtype"] = torch.float16
                self._model = AutoModelForCausalLM.from_pretrained(
                    str(model_dir),
                    **model_kwargs,
                )
                self._model.to(self._device)
                self._model.eval()
                self._last_error_type = None
                return True
            except Exception as exc:
                self._tokenizer = None
                self._model = None
                self._last_error_type = type(exc).__name__
                # The desktop build has no console. Keep the full traceback in
                # the app's redirected stdio log so packaging/runtime failures
                # can be diagnosed without exposing implementation details in
                # the normal status response.
                traceback.print_exc()
                return False


_LOCAL_INTENT_PARSER = _LocalIntentParser()
_INDEX_LOCK = threading.Lock()


def preload_intent_parser() -> None:
    """Warm up the local model in the background so the first search is fast."""

    def _run() -> None:
        try:
            _LOCAL_INTENT_PARSER._load()
        except Exception:
            pass

    thread = threading.Thread(
        target=_run,
        name="command-palette-preload",
        daemon=True,
    )
    thread.start()


def _reported_device() -> Optional[str]:
    """Return the device the local parser runs on, without forcing a load."""
    with _LOCAL_INTENT_PARSER._lock:
        device = _LOCAL_INTENT_PARSER._device
        if device:
            return device
        attempted = _LOCAL_INTENT_PARSER._attempted
    if attempted or importlib.util.find_spec("torch") is None:
        return None
    try:
        import torch
    except Exception:
        return None
    return "cuda" if torch.cuda.is_available() else "cpu"


def _merge_intents(
    query: str,
    heuristic: SearchIntent,
    model_intent: SearchIntent,
) -> SearchIntent:
    raw = unicodedata.normalize("NFKC", query or "")[:MAX_QUERY_LENGTH]
    explicit_entities = heuristic.entity_types != list(ENTITY_TYPES)
    entity_types = heuristic.entity_types if explicit_entities else model_intent.entity_types
    values = model_intent.model_dump()
    values["entity_types"] = entity_types or list(ENTITY_TYPES)
    if heuristic.text_query:
        values["text_query"] = heuristic.text_query
    gates = {
        "is_done": _DONE_TRIGGER,
        "is_favorite": _FAVORITE_TRIGGER,
        "due_from": _DUE_TRIGGER,
        "due_to": _DUE_TRIGGER,
    }
    for field in ("is_done", "is_favorite", "due_from", "due_to"):
        heuristic_value = getattr(heuristic, field)
        if heuristic_value is not None:
            values[field] = heuristic_value
        elif gates[field].search(raw):
            values[field] = getattr(model_intent, field)
        else:
            values[field] = None
    return SearchIntent.model_validate(values)


def parse_query(query: str, use_ai: bool = True) -> tuple[SearchIntent, str]:
    heuristic = _heuristic_intent(query)
    if use_ai:
        model_intent = _LOCAL_INTENT_PARSER.parse(query)
        if model_intent is not None:
            return _merge_intents(query, heuristic, model_intent), "lfm2.5-350m"
    return heuristic, "heuristic"


def _build_documents(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    documents: list[tuple[Any, ...]] = []

    clip_rows = conn.execute(
        """
        SELECT c.id, c.title, c.url, c.comment, c.is_favorite, c.created_at,
               c.project_id, cat.name AS category_name,
               COALESCE((SELECT group_concat(t.name, ' ')
                         FROM tags t JOIN clip_tags ct ON ct.tag_id = t.id
                         WHERE ct.clip_id = c.id), '') AS tag_names,
               COALESCE((SELECT group_concat(p.name, ' ')
                         FROM projects p JOIN project_clips pc ON pc.project_id = p.id
                         WHERE pc.clip_id = c.id), '') AS project_names
        FROM clips c
        LEFT JOIN categories cat ON cat.id = c.category_id
        """
    ).fetchall()
    for row in clip_rows:
        title = (row["title"] or row["url"] or "無題のクリップ").strip()
        content = _text(
            row["comment"],
            row["url"],
            row["category_name"],
            row["tag_names"],
            row["project_names"],
        )
        documents.append(
            ("clip", row["id"], title, content, None, row["is_favorite"], None, None, row["created_at"], None, row["project_id"])
        )

    task_rows = conn.execute(
        """
        SELECT t.id, t.title, t.is_done, t.due_date, t.priority, t.created_at,
               t.project_id, p.name AS project_name,
               COALESCE(c.title, c.url, '') AS clip_name,
               COALESCE((SELECT group_concat(n.title, ' ')
                         FROM notes n JOIN task_notes tn ON tn.note_id = n.id
                         WHERE tn.task_id = t.id), '') AS note_names
        FROM tasks t
        LEFT JOIN projects p ON p.id = t.project_id
        LEFT JOIN clips c ON c.id = t.clip_id
        """
    ).fetchall()
    for row in task_rows:
        title = (row["title"] or "無題のタスク").strip()
        content = _text(row["project_name"], row["clip_name"], row["note_names"])
        documents.append(
            ("task", row["id"], title, content, row["is_done"], None, row["due_date"], row["priority"], row["created_at"], None, row["project_id"])
        )

    note_rows = conn.execute(
        """
        SELECT n.id, n.title, n.body, n.is_done, n.created_at, n.updated_at,
               n.project_id,
               COALESCE((SELECT group_concat(p.name, ' ')
                         FROM projects p JOIN project_notes pn ON pn.project_id = p.id
                         WHERE pn.note_id = n.id), '') AS project_names,
               COALESCE((SELECT group_concat(COALESCE(c.title, c.url), ' ')
                         FROM clips c JOIN note_clips nc ON nc.clip_id = c.id
                         WHERE nc.note_id = n.id), '') AS clip_names
        FROM notes n
        """
    ).fetchall()
    for row in note_rows:
        title = (row["title"] or "無題のメモ").strip()
        content = _text(row["body"], row["project_names"], row["clip_names"])
        documents.append(
            ("note", row["id"], title, content, row["is_done"], None, None, None, row["created_at"], row["updated_at"], row["project_id"])
        )

    project_rows = conn.execute(
        """
        SELECT p.id, p.name, p.description, p.is_done, p.created_at,
               COALESCE((SELECT group_concat(COALESCE(c.title, c.url), ' ')
                         FROM clips c JOIN project_clips pc ON pc.clip_id = c.id
                         WHERE pc.project_id = p.id), '') AS clip_names,
               COALESCE((SELECT group_concat(t.title, ' ')
                         FROM tasks t WHERE t.project_id = p.id), '') AS task_names,
               COALESCE((SELECT group_concat(n.title, ' ')
                         FROM notes n JOIN project_notes pn ON pn.note_id = n.id
                         WHERE pn.project_id = p.id), '') AS note_names
        FROM projects p
        """
    ).fetchall()
    for row in project_rows:
        title = (row["name"] or "無題のプロジェクト").strip()
        content = _text(row["description"], row["clip_names"], row["task_names"], row["note_names"])
        documents.append(
            ("project", row["id"], title, content, row["is_done"], None, None, None, row["created_at"], None, row["id"])
        )

    return documents


def rebuild_search_index(conn: sqlite3.Connection) -> None:
    """Rebuild the denormalized search rows after source data changes."""
    fts_available = ensure_search_schema(conn)
    documents = _build_documents(conn)
    conn.execute("DELETE FROM search_documents")
    conn.executemany(
        """
        INSERT INTO search_documents(
            entity_type, entity_id, title, content, is_done, is_favorite,
            due_date, priority, created_at, updated_at, project_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        documents,
    )
    if fts_available:
        conn.execute("DELETE FROM search_documents_fts")
        conn.executemany(
            """
            INSERT INTO search_documents_fts(entity_type, entity_id, title, content)
            VALUES (?, ?, ?, ?)
            """,
            [(item[0], item[1], item[2], item[3]) for item in documents],
        )
    conn.execute(
        "INSERT OR REPLACE INTO search_index_meta(key, value) VALUES ('dirty', '0')"
    )
    # Rebuild_search_index rewrites every search_documents row, so any cached
    # semantic embeddings are stale until embedding_search re-embeds them.
    conn.execute(
        "INSERT OR REPLACE INTO search_index_meta(key, value) VALUES ('embeddings_ready', '0')"
    )


def _ensure_fresh_index(conn: sqlite3.Connection) -> bool:
    ensure_search_schema(conn)
    dirty = conn.execute(
        "SELECT value FROM search_index_meta WHERE key = 'dirty'"
    ).fetchone()
    if dirty and dirty["value"] == "1":
        with _INDEX_LOCK:
            dirty = conn.execute(
                "SELECT value FROM search_index_meta WHERE key = 'dirty'"
            ).fetchone()
            if dirty and dirty["value"] == "1":
                rebuild_search_index(conn)
                conn.commit()
    fts = conn.execute(
        "SELECT value FROM search_index_meta WHERE key = 'fts_available'"
    ).fetchone()
    return bool(fts and fts["value"] == "1")


def _terms(value: str) -> list[str]:
    normalized = _normalize(value)
    if not normalized:
        return []
    parts: list[str] = []
    for segment in _PARTICLE_SPLIT_RE.split(normalized):
        if not segment:
            continue
        if segment.isascii():
            parts.extend(word for word in re.split(r"\s+", segment) if word)
        else:
            parts.extend(part for part in re.split(r"\s+", segment) if part)
    return list(dict.fromkeys(parts))


def _fts_scores(
    conn: sqlite3.Connection,
    required_terms: list[str],
    fts_available: bool,
) -> dict[tuple[str, int], float]:
    if not fts_available or not required_terms:
        return {}
    query = " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in required_terms)
    if not query:
        return {}
    try:
        rows = conn.execute(
            """
            SELECT entity_type, entity_id, bm25(search_documents_fts) AS rank
            FROM search_documents_fts
            WHERE search_documents_fts MATCH ?
            """,
            (query,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {
        (row["entity_type"], int(row["entity_id"])): max(0.0, 30.0 + float(row["rank"] or 0))
        for row in rows
    }


def _snippet(content: str, query: str) -> Optional[str]:
    clean = re.sub(r"\s+", " ", content or "").strip()
    if not clean:
        return None
    terms = _terms(query)
    position = -1
    for term in terms:
        position = _normalize(clean).find(term)
        if position >= 0:
            break
    if position < 0:
        return clean[:160] + ("…" if len(clean) > 160 else "")
    start = max(0, position - 60)
    text = clean[start : start + 160]
    return ("…" if start else "") + text + ("…" if start + 160 < len(clean) else "")


def search_command_palette(
    conn: sqlite3.Connection,
    request: CommandPaletteSearchRequest,
) -> CommandPaletteSearchOut:
    from embedding_search import search_command_palette_embedding

    try:
        semantic = search_command_palette_embedding(
            conn,
            request.query,
            limit=request.limit,
            entity_types=request.entity_types,
            use_ai=request.use_ai,
        )
        if semantic is not None:
            return semantic
    except Exception:
        traceback.print_exc()

    fts_available = _ensure_fresh_index(conn)
    intent, parser = parse_query(request.query, use_ai=request.use_ai)
    device = _reported_device() if parser == "lfm2.5-350m" else None
    entity_types = [item for item in intent.entity_types if item in ENTITY_TYPES]
    if request.entity_types:
        entity_types = [item for item in request.entity_types if item in ENTITY_TYPES]
    if not entity_types:
        entity_types = list(ENTITY_TYPES)

    where = [
        "entity_type IN ({})".format(",".join("?" for _ in entity_types))
    ]
    params: list[Any] = list(entity_types)
    if intent.is_done is not None:
        where.append("is_done = ?")
        params.append(1 if intent.is_done else 0)
    if intent.is_favorite is True:
        where.append("is_favorite = 1")
    elif intent.is_favorite is False:
        # Tasks, notes, and projects do not currently expose a favorite flag.
        # Treat their NULL as not-favorite instead of hiding them from a
        # negative favorite filter.
        where.append("(is_favorite = 0 OR is_favorite IS NULL)")
    if intent.due_from:
        where.append("due_date IS NOT NULL AND due_date >= ?")
        params.append(intent.due_from)
    if intent.due_to:
        where.append("due_date IS NOT NULL AND due_date <= ?")
        params.append(intent.due_to)
    for field in ("project_name", "category", "tag"):
        value = getattr(intent, field)
        if value:
            where.append("(LOWER(title) LIKE ? OR LOWER(content) LIKE ?)")
            wildcard = f"%{_normalize(value)}%"
            params.extend((wildcard, wildcard))

    text_query = intent.text_query.strip()
    required_terms, optional_terms = _query_slots(text_query)
    for term in required_terms:
        variants = _term_variants(term)
        where.append(
            "("
            + " OR ".join(
                "(LOWER(title) LIKE ? OR LOWER(content) LIKE ?)" for _ in variants
            )
            + ")"
        )
        for variant in variants:
            wildcard = f"%{_normalize(variant)}%"
            params.extend((wildcard, wildcard))

    rows = conn.execute(
        "SELECT * FROM search_documents WHERE " + " AND ".join(where),
        params,
    ).fetchall()
    fts_scores = _fts_scores(conn, required_terms, fts_available)

    ranked: list[tuple[float, sqlite3.Row]] = []
    normalized_query = _normalize(text_query)
    for row in rows:
        title = _normalize(row["title"])
        content = _normalize(row["content"])
        score = fts_scores.get((row["entity_type"], int(row["entity_id"])), 0.0)
        if normalized_query and title == normalized_query:
            score += 150.0
        elif normalized_query and normalized_query in title:
            score += 90.0
        if normalized_query and normalized_query in content:
            score += 30.0
        for term in optional_terms:
            if term in title or term in content:
                score += 20.0
        if row["due_date"] and intent.due_from:
            score += 8.0
        ranked.append((score, row))
    ranked.sort(key=lambda item: (item[0], item[1]["created_at"] or ""), reverse=True)

    results: list[CommandPaletteResultOut] = []
    targets = {
        "clip": "/Home?clip_id={id}",
        "note": "/Note?id={id}",
        "task": "/Notes?task_id={id}",
        "project": "/Projects?id={id}",
    }
    for _score, row in ranked[: min(request.limit, intent.limit, 50)]:
        results.append(
            CommandPaletteResultOut(
                entity_type=row["entity_type"],
                id=int(row["entity_id"]),
                title=row["title"],
                snippet=_snippet(row["content"], text_query),
                target=targets[row["entity_type"]].format(id=int(row["entity_id"])),
                is_done=None if row["is_done"] is None else bool(row["is_done"]),
                is_favorite=None if row["is_favorite"] is None else bool(row["is_favorite"]),
                due_date=row["due_date"],
                priority=row["priority"],
            )
        )

    return CommandPaletteSearchOut(
        query=request.query,
        parser=parser,
        search_mode="fts+like" if fts_available else "like",
        intent=intent,
        total=len(ranked),
        results=results,
        device=device,
    )


def get_command_palette_status() -> CommandPaletteStatusOut:
    source = _configured_model_source()
    transformers_available = importlib.util.find_spec("transformers") is not None
    torch_available = importlib.util.find_spec("torch") is not None
    configured = bool(source)
    model_dir: Optional[Path] = None
    gguf_file: Optional[str] = None
    source_exists = False
    metadata_ready = True
    if source:
        model_dir, gguf_file = _resolve_model_files(source)
        source_exists = Path(source).exists()
        if gguf_file:
            metadata_ready = all(
                (model_dir / filename).is_file()
                for filename in ("config.json", "tokenizer.json", "tokenizer_config.json")
            )
    gguf_runtime_available = gguf_file is None or (
        importlib.util.find_spec("gguf") is not None
        and importlib.util.find_spec("accelerate") is not None
    )
    device: Optional[str] = None
    with _LOCAL_INTENT_PARSER._lock:
        model_loaded = _LOCAL_INTENT_PARSER._model is not None
        device = _LOCAL_INTENT_PARSER._device or device
    available = (
        configured
        and source_exists
        and metadata_ready
        and transformers_available
        and torch_available
        and gguf_runtime_available
    )
    if not configured:
        message = "モデル未設定。通常検索を使用します。"
    elif not source_exists:
        message = "モデルパスが見つかりません。通常検索を使用します。"
    elif not metadata_ready:
        message = "GGUF用の設定・トークナイザーが不足しています。"
    elif not transformers_available or not torch_available:
        message = "torch/transformers未導入。通常検索を使用します。"
    elif not gguf_runtime_available:
        message = "GGUF用のgguf/accelerateが未導入です。"
    elif _LOCAL_INTENT_PARSER._last_error_type:
        message = f"モデル初期化失敗（{_LOCAL_INTENT_PARSER._last_error_type}）。"
    else:
        message = (
            "ローカルGGUFモデルを使用できます。"
            if gguf_file
            else "ローカルモデルを使用できます。"
        )

    from embedding_search import embedding_model_status

    embedding = embedding_model_status()
    return CommandPaletteStatusOut(
        model_id=MODEL_ID,
        backend="transformers-gguf" if gguf_file else "transformers",
        configured=configured,
        available=available,
        device=device,
        model_loaded=model_loaded,
        message=message,
        embedding_available=embedding["available"],
        embedding_device=embedding["device"],
        embedding_model_loaded=embedding["model_loaded"],
    )
