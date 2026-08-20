"""Semantic search over the command palette using the local Embedding Gemma.

The intent parser (LFM2.5-350M) turns a query into filters; this module adds a
semantic ranking layer on top of the same candidate rows.  Each search document
is embedded once with the locally converted Embedding Gemma 300M checkpoint and
the vectors are cached in SQLite so ranking a query only needs a single forward
pass for the query itself.

The model is loaded lazily and warmed up at startup so the first search stays
inside the 1-2 second budget.  Any failure (missing model, no torch, empty
cache) degrades to the keyword search in command_palette.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import threading
import traceback
from pathlib import Path
from typing import Any, Optional

import numpy as np

from paths import get_app_data_dir
from command_palette import (
    DEFAULT_LIMIT,
    ENTITY_TYPES,
    CommandPaletteResultOut,
    CommandPaletteSearchOut,
    SearchIntent,
    _ensure_fresh_index,
    _heuristic_intent,
    _normalize,
    _query_slots,
    _snippet,
    _term_variants,
)

EMBEDDING_MODEL_DIRECTORY_NAME = "embeddinggemma-300m"
EMBEDDING_MODEL_SOURCE = "converted"
EMBEDDING_DIM = 768
EMBEDDING_MAX_CHARS = 1500
EMBEDDING_BATCH = 64


EMBEDDING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS search_embeddings (
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    embedding BLOB NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
);

INSERT OR IGNORE INTO search_index_meta(key, value) VALUES ('embeddings_ready', '0');
"""


def _configured_embedding_source() -> Optional[str]:
    configured = os.getenv("SPARKLE_EMBEDDING_MODEL_PATH", "").strip()
    if configured:
        return configured
    default_path = get_app_data_dir() / "models" / EMBEDDING_MODEL_DIRECTORY_NAME / EMBEDDING_MODEL_SOURCE
    if default_path.exists():
        return str(default_path)
    return None


class _EmbeddingModel:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._device: Optional[str] = None
        self._attempted = False
        self._last_error_type: Optional[str] = None

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
            source = _configured_embedding_source()
            if (
                not source
                or importlib.util.find_spec("transformers") is None
                or importlib.util.find_spec("torch") is None
            ):
                return False
            try:
                import torch
                from transformers import AutoTokenizer, Gemma3TextModel

                self._torch = torch
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
                self._tokenizer = AutoTokenizer.from_pretrained(
                    source,
                    local_files_only=True,
                )
                self._model = Gemma3TextModel.from_pretrained(
                    source,
                    local_files_only=True,
                    torch_dtype=torch.bfloat16,
                )
                self._model.to(self._device)
                self._model.eval()
                self._last_error_type = None
                return True
            except Exception as exc:
                self._tokenizer = None
                self._model = None
                self._last_error_type = type(exc).__name__
                traceback.print_exc()
                return False

    def embed(self, texts: list[str]) -> Optional[np.ndarray]:
        """Return an (n, EMBEDDING_DIM) float32 array, or None on any failure."""
        if not texts or not self._load():
            return None
        try:
            tokenizer, model = self._tokenizer, self._model
            torch = self._torch
            results: list[np.ndarray] = []
            for start in range(0, len(texts), EMBEDDING_BATCH):
                batch = texts[start : start + EMBEDDING_BATCH]
                enc = tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=2048,
                    return_tensors="pt",
                )
                enc = {key: value.to(self._device) for key, value in enc.items()}
                with torch.inference_mode():
                    hidden = model(**enc).last_hidden_state
                    mask = enc["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                    pooled = (hidden * mask).sum(1) / mask.sum(1)
                    pooled = torch.nn.functional.normalize(pooled.float(), dim=-1)
                results.append(pooled.cpu().numpy())
            return np.concatenate(results, axis=0)
        except Exception as exc:
            self._last_error_type = type(exc).__name__
            return None


_EMBEDDING_MODEL = _EmbeddingModel()


def preload_embedding_model() -> None:
    """Warm up the embedding model in the background at startup."""

    def _run() -> None:
        try:
            _EMBEDDING_MODEL._load()
        except Exception:
            pass

    thread = threading.Thread(
        target=_run,
        name="command-palette-embedding-preload",
        daemon=True,
    )
    thread.start()


def embedding_model_status() -> dict[str, Any]:
    """Non-blocking snapshot of the embedding model for the status endpoint."""
    with _EMBEDDING_MODEL._lock:
        attempted = _EMBEDDING_MODEL._attempted
        loaded = _EMBEDDING_MODEL._model is not None
        device = _EMBEDDING_MODEL._device
        error = _EMBEDDING_MODEL._last_error_type
    source = _configured_embedding_source()
    transformers_available = importlib.util.find_spec("transformers") is not None
    torch_available = importlib.util.find_spec("torch") is not None
    source_exists = bool(source and Path(source).exists())
    metadata_ready = bool(
        source
        and all(
            (Path(source) / filename).is_file()
            for filename in ("config.json", "tokenizer.json", "tokenizer_config.json")
        )
    )
    if not attempted:
        try:
            import torch  # noqa: F401

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = None
    available = bool(
        source_exists
        and metadata_ready
        and transformers_available
        and torch_available
    )
    return {
        "source": source,
        "available": available,
        "model_loaded": loaded,
        "device": device,
        "error": error,
    }


def _document_text(row: sqlite3.Row) -> str:
    title = (row["title"] or "").strip()
    content = (row["content"] or "").strip()
    return (f"{title}\n{content}" if title and content else title or content)[:EMBEDDING_MAX_CHARS]


def ensure_embedding_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(EMBEDDING_SCHEMA_SQL)


def rebuild_embeddings(conn: sqlite3.Connection) -> bool:
    """Re-embed every search document and cache the vectors. Returns success."""
    if not _EMBEDDING_MODEL._load():
        return False
    ensure_embedding_schema(conn)
    rows = conn.execute("SELECT entity_type, entity_id, title, content FROM search_documents").fetchall()
    if not rows:
        conn.execute("INSERT OR REPLACE INTO search_index_meta(key, value) VALUES ('embeddings_ready', '1')")
        conn.commit()
        return True
    texts = [_document_text(row) for row in rows]
    vectors = _EMBEDDING_MODEL.embed(texts)
    if vectors is None:
        return False
    conn.execute("DELETE FROM search_embeddings")
    conn.executemany(
        "INSERT INTO search_embeddings(entity_type, entity_id, embedding) VALUES (?, ?, ?)",
        [(row["entity_type"], row["entity_id"], vectors[i].astype(np.float32).tobytes()) for i, row in enumerate(rows)],
    )
    conn.execute("INSERT OR REPLACE INTO search_index_meta(key, value) VALUES ('embeddings_ready', '1')")
    conn.commit()
    return True


def _ensure_embeddings(conn: sqlite3.Connection) -> bool:
    ensure_embedding_schema(conn)
    ready = conn.execute(
        "SELECT value FROM search_index_meta WHERE key = 'embeddings_ready'"
    ).fetchone()
    if ready and ready["value"] == "1":
        return True
    return rebuild_embeddings(conn)


def _load_vectors(
    conn: sqlite3.Connection,
    candidates: list[tuple[str, int]],
) -> dict[tuple[str, int], np.ndarray]:
    vectors: dict[tuple[str, int], np.ndarray] = {}
    if not candidates:
        return vectors
    params: list[Any] = []
    clauses: list[str] = []
    for entity_type, entity_id in candidates:
        clauses.append("(entity_type = ? AND entity_id = ?)")
        params.extend((entity_type, entity_id))
    rows = conn.execute(
        "SELECT entity_type, entity_id, embedding FROM search_embeddings WHERE "
        + " OR ".join(clauses),
        params,
    ).fetchall()
    for row in rows:
        vectors[(row["entity_type"], int(row["entity_id"]))] = np.frombuffer(
            row["embedding"], dtype=np.float32
        )
    return vectors


def _literal_boost(title: str, content: str, text_query: str, required_terms: list[str], optional_terms: list[str]) -> float:
    boost = 0.0
    normalized_query = _normalize(text_query)
    normalized_title = _normalize(title)
    normalized_content = _normalize(content)
    if normalized_query and normalized_title == normalized_query:
        boost += 0.15
    elif normalized_query and normalized_query in normalized_title:
        boost += 0.08
    if normalized_query and normalized_query in normalized_content:
        boost += 0.03
    for term in required_terms + optional_terms:
        if any(variant in normalized_title for variant in _term_variants(term)):
            boost += 0.02
    return boost


def search_command_palette_embedding(
    conn: sqlite3.Connection,
    query: str,
    limit: int = DEFAULT_LIMIT,
    entity_types: Optional[list[str]] = None,
    use_ai: bool = True,
) -> Optional[CommandPaletteSearchOut]:
    """Run semantic search. Returns None when the model or cache is unavailable.

    Filters come from the deterministic heuristic parser (the LFM intent
    parser stays in the keyword fallback path in command_palette): the
    semantic model itself is the AI layer, and the heuristic already extracts
    the same entity/status/date filters for a fraction of the latency.
    """
    if not _EMBEDDING_MODEL._load():
        return None
    _ensure_fresh_index(conn)
    if not _ensure_embeddings(conn):
        return None

    intent = _heuristic_intent(query)
    parser = "heuristic"
    entity_types = [item for item in (entity_types or intent.entity_types) if item in ENTITY_TYPES]
    if not entity_types:
        entity_types = list(ENTITY_TYPES)

    where = ["entity_type IN ({})".format(",".join("?" for _ in entity_types))]
    params: list[Any] = list(entity_types)
    if intent.is_done is not None:
        where.append("is_done = ?")
        params.append(1 if intent.is_done else 0)
    if intent.is_favorite is True:
        where.append("is_favorite = 1")
    elif intent.is_favorite is False:
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

    rows = conn.execute(
        "SELECT * FROM search_documents WHERE " + " AND ".join(where),
        params,
    ).fetchall()
    if not rows:
        return _empty_out(query, parser, intent, entity_types)

    candidates = [(row["entity_type"], int(row["entity_id"])) for row in rows]
    vectors = _load_vectors(conn, candidates)
    if not vectors:
        return None

    text_query = intent.text_query.strip()
    embed_text = text_query or query.strip()
    query_vector = _EMBEDDING_MODEL.embed([embed_text])
    if query_vector is None:
        return None
    query_vector = query_vector[0]

    required_terms, optional_terms = _query_slots(text_query)
    ranked: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        vector = vectors.get((row["entity_type"], int(row["entity_id"])))
        if vector is None:
            continue
        score = float(np.dot(query_vector, vector))
        score += _literal_boost(row["title"], row["content"], text_query, required_terms, optional_terms)
        ranked.append((score, row))
    ranked.sort(key=lambda item: (item[0], item[1]["created_at"] or ""), reverse=True)

    targets = {
        "clip": "/Home?clip_id={id}",
        "note": "/Note?id={id}",
        "task": "/Notes?task_id={id}",
        "project": "/Projects?id={id}",
    }
    results: list[CommandPaletteResultOut] = []
    for score, row in ranked[: min(limit, intent.limit, 50)]:
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
                score=score,
            )
        )

    device = embedding_model_status().get("device")
    return CommandPaletteSearchOut(
        query=query,
        parser=parser,
        search_mode="embedding",
        intent=intent,
        total=len(ranked),
        results=results,
        device=device,
    )


def _empty_out(
    query: str,
    parser: str,
    intent: SearchIntent,
    entity_types: list[str],
) -> CommandPaletteSearchOut:
    return CommandPaletteSearchOut(
        query=query,
        parser=parser,
        search_mode="embedding",
        intent=intent,
        total=0,
        results=[],
        device=embedding_model_status().get("device"),
    )