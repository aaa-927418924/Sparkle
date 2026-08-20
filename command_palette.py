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
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from paths import get_app_data_dir


MODEL_ID = "LiquidAI/LFM2.5-350M"
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


class CommandPaletteSearchOut(BaseModel):
    query: str
    parser: str
    search_mode: str
    intent: SearchIntent
    total: int
    results: list[CommandPaletteResultOut]


class CommandPaletteStatusOut(BaseModel):
    model_id: str
    backend: str
    configured: bool
    available: bool
    message: str


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
    default_path = get_app_data_dir() / "models" / "LFM2.5-350M"
    if default_path.exists():
        return str(default_path)
    return None


class _LocalIntentParser:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._device = None
        self._attempted = False

    def parse(self, query: str) -> Optional[SearchIntent]:
        if not self._load():
            return None
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are Sparkle's Japanese search parser. "
                        "Return JSON only. Never answer the user and never write SQL. "
                        "Allowed entity_types are clip, note, task, project. "
                        "Use ISO dates when a date filter is explicit. "
                        "Schema: entity_types(array), text_query(string), is_done(boolean|null), "
                        "is_favorite(boolean|null), due_from(string|null), due_to(string|null), "
                        "project_name(string|null), category(string|null), tag(string|null), limit(number)."
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
                    max_new_tokens=192,
                    do_sample=False,
                    pad_token_id=self._tokenizer.eos_token_id,
                )
            generated = output[0][input_length:]
            text = self._tokenizer.decode(generated, skip_special_tokens=True).strip()
            start = text.find("{")
            if start < 0:
                return None
            payload, _ = json.JSONDecoder().raw_decode(text[start:])
            return SearchIntent.model_validate(payload)
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
            if not source or importlib.util.find_spec("transformers") is None:
                return False
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer

                self._torch = torch
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
                kwargs: dict[str, Any] = {"local_files_only": True}
                if self._device == "cuda":
                    kwargs["torch_dtype"] = torch.float16
                self._tokenizer = AutoTokenizer.from_pretrained(source, **kwargs)
                self._model = AutoModelForCausalLM.from_pretrained(source, **kwargs)
                self._model.to(self._device)
                self._model.eval()
                return True
            except Exception:
                self._tokenizer = None
                self._model = None
                return False


_LOCAL_INTENT_PARSER = _LocalIntentParser()
_INDEX_LOCK = threading.Lock()


def _merge_intents(heuristic: SearchIntent, model_intent: SearchIntent) -> SearchIntent:
    explicit_entities = heuristic.entity_types != list(ENTITY_TYPES)
    entity_types = heuristic.entity_types if explicit_entities else model_intent.entity_types
    values = model_intent.model_dump()
    values["entity_types"] = entity_types or list(ENTITY_TYPES)
    if heuristic.text_query:
        values["text_query"] = heuristic.text_query
    for field in ("is_done", "is_favorite", "due_from", "due_to"):
        value = getattr(heuristic, field)
        if value is not None:
            values[field] = value
    return SearchIntent.model_validate(values)


def parse_query(query: str, use_ai: bool = True) -> tuple[SearchIntent, str]:
    heuristic = _heuristic_intent(query)
    if use_ai:
        model_intent = _LOCAL_INTENT_PARSER.parse(query)
        if model_intent is not None:
            return _merge_intents(heuristic, model_intent), "lfm2.5-350m"
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
    parts = [part for part in re.split(r"\s+", normalized) if len(part) >= 1]
    return list(dict.fromkeys(parts))


def _fts_scores(conn: sqlite3.Connection, text_query: str, fts_available: bool) -> dict[tuple[str, int], float]:
    if not fts_available or not text_query:
        return {}
    query = " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in _terms(text_query))
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
    fts_available = _ensure_fresh_index(conn)
    intent, parser = parse_query(request.query, use_ai=request.use_ai)
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
    terms = _terms(text_query)
    for term in terms:
        where.append("(LOWER(title) LIKE ? OR LOWER(content) LIKE ?)")
        wildcard = f"%{term}%"
        params.extend((wildcard, wildcard))

    rows = conn.execute(
        "SELECT * FROM search_documents WHERE " + " AND ".join(where),
        params,
    ).fetchall()
    fts_scores = _fts_scores(conn, text_query, fts_available)

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
    )


def get_command_palette_status() -> CommandPaletteStatusOut:
    source = _configured_model_source()
    transformers_available = importlib.util.find_spec("transformers") is not None
    configured = bool(source)
    available = configured and transformers_available
    if not configured:
        message = "モデル未設定。通常検索を使用します。"
    elif not transformers_available:
        message = "transformers未導入。通常検索を使用します。"
    else:
        message = "ローカルモデルを使用できます。"
    return CommandPaletteStatusOut(
        model_id=MODEL_ID,
        backend="transformers",
        configured=configured,
        available=available,
        message=message,
    )
