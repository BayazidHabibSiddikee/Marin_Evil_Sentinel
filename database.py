import psycopg2
from psycopg2.extras import DictCursor
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager

# Defaults assuming local postgres instance
DB_NAME = os.getenv("PG_DB_NAME", "postgres")
DB_USER = os.getenv("PG_USER", "postgres")
DB_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
DB_HOST = os.getenv("PG_HOST", "localhost")
DB_PORT = os.getenv("PG_PORT", "5432")

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(1, 20,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
    return _pool

@contextmanager
def get_connection():
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Chat History Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                agent VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Timers Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS timers (
                id SERIAL PRIMARY KEY,
                task VARCHAR(255) NOT NULL,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP,
                duration_minutes INTEGER,
                status VARCHAR(50) DEFAULT 'active'
            )
        ''')
        
        # User State Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_state (
                key VARCHAR(255) PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # News Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS news (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT,
                analysis TEXT,
                source VARCHAR(255) DEFAULT 'AlJazeera',
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Flashcards Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS flashcards (
                id SERIAL PRIMARY KEY,
                topic VARCHAR(255) NOT NULL,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                next_review TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                interval_days INTEGER DEFAULT 1,
                ease_factor REAL DEFAULT 2.5,
                reviews INTEGER DEFAULT 0
            )
        ''')
        
        # Study Sessions Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS study_sessions (
                id SERIAL PRIMARY KEY,
                topic VARCHAR(255) NOT NULL,
                focus_minutes INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Penalties Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS penalties (
                id SERIAL PRIMARY KEY,
                task TEXT NOT NULL,
                status VARCHAR(50) DEFAULT 'active',
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cleared_at TIMESTAMP
            )
        ''')
        
        conn.commit()

        # Vault Table (user knowledge store)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vault (
                id SERIAL PRIMARY KEY,
                category VARCHAR(100) NOT NULL,
                key VARCHAR(255) NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                source VARCHAR(50) DEFAULT 'observed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, key)
            )
        ''')
        
        conn.commit()

# ── Vault API ────────────────────────────────────────────────────────────────
VAULT_MAX_BYTES = 2 * 1024 * 1024  # 2MB

def vault_get_all() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT category, key, value, confidence, source FROM vault ORDER BY category, key")
        return [dict(r) for r in cursor.fetchall()]

def vault_get_by_category(category: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT key, value, confidence, source FROM vault WHERE category = %s ORDER BY key", (category,))
        return [dict(r) for r in cursor.fetchall()]

def vault_get(category: str, key: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT value, confidence, source FROM vault WHERE category = %s AND key = %s", (category, key))
        row = cursor.fetchone()
        return dict(row) if row else None

def vault_current_size() -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(SUM(LENGTH(category) + LENGTH(key) + LENGTH(value) + 100), 0) FROM vault")
        return cursor.fetchone()[0]

def vault_upsert(category: str, key: str, value: str, confidence: float = 1.0, source: str = "observed") -> bool:
    current = vault_current_size()
    new_bytes = len(category.encode()) + len(key.encode()) + len(value.encode()) + 100
    if current + new_bytes > VAULT_MAX_BYTES:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO vault (category, key, value, confidence, source) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (category, key) DO UPDATE SET value = EXCLUDED.value, confidence = EXCLUDED.confidence, "
            "source = EXCLUDED.source, updated_at = CURRENT_TIMESTAMP",
            (category, key, value, confidence, source)
        )
        conn.commit()
    return True

def vault_delete(category: str, key: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM vault WHERE category = %s AND key = %s", (category, key))
        conn.commit()

def vault_search(query: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute(
            "SELECT category, key, value, confidence FROM vault WHERE value ILIKE %s OR key ILIKE %s ORDER BY category LIMIT 20",
            (f"%{query}%", f"%{query}%")
        )
        return [dict(r) for r in cursor.fetchall()]

def vault_as_context() -> str:
    rows = vault_get_all()
    if not rows:
        return ""
    lines = ["[USER KNOWLEDGE VAULT — important facts about the user]"]
    current_cat = ""
    for r in rows:
        if r["category"] != current_cat:
            current_cat = r["category"]
            lines.append(f"\n## {current_cat}")
        lines.append(f"- {r['key']}: {r['value']}")
    return "\n".join(lines)

# ── Chat History API ─────────────────────────────────────────────────────────

def save_message(agent: str, role: str, content: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_history (agent, role, content) VALUES (%s, %s, %s)",
            (agent, role, content)
        )
        conn.commit()

def get_history(agent: str, limit: int = 50) -> List[Dict[str, str]]:
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute(
            "SELECT role, content FROM chat_history WHERE agent = %s AND timestamp >= NOW() - INTERVAL '14 days' ORDER BY timestamp DESC LIMIT %s",
            (agent, limit)
        )
        rows = cursor.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

def clear_history(agent: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_history WHERE agent = %s", (agent,))
        conn.commit()

def prune_old_messages():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_history WHERE timestamp < NOW() - INTERVAL '14 days'")
        conn.commit()

# ── Timers API ────────────────────────────────────────────────────────────────

def start_timer(task: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        start_time = datetime.now()
        cursor.execute(
            "INSERT INTO timers (task, start_time, status) VALUES (%s, %s, 'active') RETURNING id",
            (task, start_time)
        )
        timer_id = cursor.fetchone()[0]
        conn.commit()
    return timer_id

def end_timer(timer_id: int, status: str = 'completed'):
    with get_connection() as conn:
        cursor = conn.cursor()
        end_time = datetime.now()
        
        cursor.execute("SELECT start_time FROM timers WHERE id = %s", (timer_id,))
        row = cursor.fetchone()
        if row:
            start_time = row[0]
            duration = int((end_time - start_time).total_seconds() / 60)
            cursor.execute(
                "UPDATE timers SET end_time = %s, duration_minutes = %s, status = %s WHERE id = %s",
                (end_time, duration, status, timer_id)
            )
        conn.commit()

def get_timer_stats():
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT * FROM timers ORDER BY start_time DESC LIMIT 20")
        rows = cursor.fetchall()
    return [dict(r) for r in rows]

# ── User State API ───────────────────────────────────────────────────────────

def set_state(key: str, value: Any):
    with get_connection() as conn:
        cursor = conn.cursor()
        val_str = json.dumps(value)
        cursor.execute(
            "INSERT INTO user_state (key, value, updated_at) VALUES (%s, %s, CURRENT_TIMESTAMP) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP",
            (key, val_str)
        )
        conn.commit()

def get_state(key: str, default: Any = None) -> Any:
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT value FROM user_state WHERE key = %s", (key,))
        row = cursor.fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]

# ── Penalties API ────────────────────────────────────────────────────────────

def assign_penalty(task: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO penalties (task, status) VALUES (%s, 'active') RETURNING id",
            (task,)
        )
        conn.commit()

def get_active_penalty() -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT * FROM penalties WHERE status = 'active' ORDER BY assigned_at DESC LIMIT 1")
        row = cursor.fetchone()
    if row:
        return dict(row)
    return None

def clear_penalty():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE penalties SET status = 'completed', cleared_at = CURRENT_TIMESTAMP WHERE status = 'active'")
        conn.commit()

if __name__ == "__main__":
    init_db()
    print("PostgreSQL Database initialized.")
