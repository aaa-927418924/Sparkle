"""CRUD helpers for categories and tags."""

from sqlite3 import Connection

from db import get_connection


def get_or_create_category(conn: Connection, name: str) -> int:
    cur = conn.execute("SELECT id FROM categories WHERE name = ?", (name,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO categories(name) VALUES (?)", (name,))
    return cur.lastrowid


def get_or_create_tag(conn: Connection, name: str) -> int:
    cur = conn.execute("SELECT id FROM tags WHERE name = ?", (name,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO tags(name) VALUES (?)", (name,))
    return cur.lastrowid
