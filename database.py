import sqlite3
from datetime import datetime

DB_PATH = "dwfs.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clientDetails (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name     TEXT NOT NULL UNIQUE,
                broker          TEXT NOT NULL,
                port            INTEGER NOT NULL,
                client_id       TEXT,
                topic_telemetry TEXT,
                topic_attribute TEXT,
                topic_subscribe TEXT,
                topic_sharedkey TEXT,
                username        TEXT,
                password        TEXT,
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pubHistory (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                client       TEXT NOT NULL,
                publishTopic TEXT NOT NULL,
                payload      TEXT,
                payload_size INTEGER,
                datetime     DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS connectionHistory (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                client           TEXT NOT NULL,
                connected_time   DATETIME,
                disconnected_time DATETIME,
                mode             TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subHistory (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                client       TEXT NOT NULL,
                topic        TEXT NOT NULL,
                payload      TEXT,
                payload_size INTEGER,
                datetime     DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS appState (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS widget_triggers (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                UNIQUE(source_id, target_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                client     TEXT NOT NULL,
                topic      TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(client, topic)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS widgets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL DEFAULT 'Widget',
                widget_type TEXT NOT NULL DEFAULT 'publish',
                topic       TEXT NOT NULL DEFAULT '',
                key         TEXT DEFAULT '',
                value_type  TEXT DEFAULT 'string',
                value       TEXT DEFAULT '',
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # migrate existing DB: add columns if missing
        for col_def in [
            "ALTER TABLE widgets ADD COLUMN key           TEXT    DEFAULT ''",
            "ALTER TABLE widgets ADD COLUMN color         TEXT    DEFAULT ''",
            "ALTER TABLE widgets ADD COLUMN timer_enabled INTEGER DEFAULT 0",
            "ALTER TABLE widgets ADD COLUMN timer_hh      INTEGER DEFAULT 0",
            "ALTER TABLE widgets ADD COLUMN timer_mm      INTEGER DEFAULT 0",
            "ALTER TABLE widgets ADD COLUMN timer_ss      INTEGER DEFAULT 5",
            "ALTER TABLE widgets ADD COLUMN value_mode    TEXT    DEFAULT 'static'",
            "ALTER TABLE widgets ADD COLUMN val_from      TEXT    DEFAULT '0'",
            "ALTER TABLE widgets ADD COLUMN val_to        TEXT    DEFAULT '100'",
            "ALTER TABLE widgets ADD COLUMN val_step      TEXT    DEFAULT '1'",
            "ALTER TABLE widgets ADD COLUMN client_name   TEXT    DEFAULT ''",
            "ALTER TABLE widgets ADD COLUMN sub_method       TEXT    DEFAULT ''",
            "ALTER TABLE widgets ADD COLUMN sub_filter_value TEXT    DEFAULT ''",
            "ALTER TABLE widgets ADD COLUMN alert_sound      INTEGER DEFAULT 0",
            "ALTER TABLE widgets ADD COLUMN rpc_response     TEXT    DEFAULT '{\"result\": \"ok\"}'",
            "ALTER TABLE widgets ADD COLUMN extra_payload    TEXT    DEFAULT ''",
            "ALTER TABLE widgets ADD COLUMN pos_x           INTEGER DEFAULT 0",
            "ALTER TABLE widgets ADD COLUMN pos_y           INTEGER DEFAULT 0",
            "ALTER TABLE widgets ADD COLUMN width           INTEGER DEFAULT 151",
            "ALTER TABLE widgets ADD COLUMN height          INTEGER DEFAULT 151",
            "ALTER TABLE widgets ADD COLUMN shape           TEXT    DEFAULT 'square'",
            "ALTER TABLE pubHistory ADD COLUMN status TEXT DEFAULT 'ok'",
            "ALTER TABLE widgets ADD COLUMN indicator     INTEGER DEFAULT 0",
            "ALTER TABLE widgets ADD COLUMN indicator_key TEXT    DEFAULT ''",
            "ALTER TABLE widgets ADD COLUMN display_val   INTEGER DEFAULT 0",
            "ALTER TABLE widgets ADD COLUMN display_key   TEXT    DEFAULT ''",
            "ALTER TABLE widgets ADD COLUMN bulb_color    TEXT    DEFAULT ''",
            "ALTER TABLE widgets ADD COLUMN display_color TEXT    DEFAULT ''",
        ]:
            try:
                conn.execute(col_def)
            except Exception:
                pass
        # migrate widget_triggers: add delay_ms if missing
        try:
            conn.execute("ALTER TABLE widget_triggers ADD COLUMN delay_ms INTEGER DEFAULT 0")
        except Exception:
            pass
        conn.commit()


# ── widgets ────────────────────────────────────────────────
_WIDGET_FIELDS = ["name", "widget_type", "topic", "key", "value_type", "value", "color",
                  "timer_enabled", "timer_hh", "timer_mm", "timer_ss",
                  "value_mode", "val_from", "val_to", "val_step", "client_name",
                  "sub_method", "sub_filter_value", "alert_sound", "rpc_response", "extra_payload",
                  "pos_x", "pos_y", "width", "height", "shape",
                  "indicator", "indicator_key", "display_val", "display_key",
                  "bulb_color", "display_color"]

def get_widgets():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM widgets ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


def create_widget(data: dict) -> int:
    cols   = ", ".join(_WIDGET_FIELDS)
    placeholders = ", ".join("?" for _ in _WIDGET_FIELDS)
    values = [data.get(f, "") for f in _WIDGET_FIELDS]
    with get_connection() as conn:
        cursor = conn.execute(f"INSERT INTO widgets ({cols}) VALUES ({placeholders})", values)
        conn.commit()
        return cursor.lastrowid


def update_widget(widget_id: int, data: dict):
    set_clause = ", ".join(f"{f} = ?" for f in _WIDGET_FIELDS)
    values = [data.get(f, "") for f in _WIDGET_FIELDS] + [widget_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE widgets SET {set_clause} WHERE id = ?", values)
        conn.commit()


def update_widget_position(widget_id: int, pos_x: int, pos_y: int,
                           width: int = None, height: int = None):
    sets = ["pos_x = ?", "pos_y = ?"]
    vals = [pos_x, pos_y]
    if width is not None:
        sets.append("width = ?"); vals.append(width)
    if height is not None:
        sets.append("height = ?"); vals.append(height)
    vals.append(widget_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE widgets SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()


def delete_widget(widget_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM widgets WHERE id = ?", (widget_id,))
        conn.commit()


def import_widgets(widget_list: list):
    conn = get_connection()
    try:
        for w in widget_list:
            cols   = ", ".join(_WIDGET_FIELDS)
            placeholders = ", ".join("?" for _ in _WIDGET_FIELDS)
            values = [w.get(f, "") for f in _WIDGET_FIELDS]
            conn.execute(f"INSERT INTO widgets ({cols}) VALUES ({placeholders})", values)
        conn.commit()
    finally:
        conn.close()


# ── clientDetails ──────────────────────────────────────────
def get_all_clients():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM clientDetails ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_client(client_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM clientDetails WHERE id = ?", (client_id,)).fetchone()
    return dict(row) if row else None


def create_client(data: dict):
    fields = ["client_name", "broker", "port", "client_id", "topic_telemetry",
              "topic_attribute", "topic_subscribe", "topic_sharedkey", "username", "password"]
    cols = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    values = [data.get(f, "") for f in fields]
    with get_connection() as conn:
        cursor = conn.execute(f"INSERT INTO clientDetails ({cols}) VALUES ({placeholders})", values)
        conn.commit()
        return cursor.lastrowid


def update_client(record_id: int, data: dict):
    fields = ["client_name", "broker", "port", "client_id", "topic_telemetry",
              "topic_attribute", "topic_subscribe", "topic_sharedkey", "username", "password"]
    set_clause = ", ".join(f"{f} = ?" for f in fields)
    values = [data.get(f, "") for f in fields] + [record_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE clientDetails SET {set_clause} WHERE id = ?", values)
        conn.commit()


def delete_client(record_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM clientDetails WHERE id = ?", (record_id,))
        conn.commit()


# ── pubHistory ─────────────────────────────────────────────
def log_publish(client: str, topic: str, payload: str, status: str = "ok"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO pubHistory (client, publishTopic, payload, payload_size, datetime, status) VALUES (?, ?, ?, ?, ?, ?)",
            (client, topic, payload, len(payload.encode()), now, status)
        )
        conn.commit()


def delete_history_records(records: list):
    """records: list of {type, id}"""
    type_table = {"pub": "pubHistory", "sub": "subHistory", "conn": "connectionHistory"}
    conn = get_connection()
    try:
        for rec in records:
            table = type_table.get(rec.get("type"))
            if table and rec.get("id"):
                conn.execute(f"DELETE FROM {table} WHERE id = ?", (int(rec["id"]),))
        conn.commit()
    finally:
        conn.close()


def get_pub_history(limit: int = 1000):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM pubHistory ORDER BY datetime DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── subHistory ────────────────────────────────────────────
def log_subscribe(client: str, topic: str, payload: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO subHistory (client, topic, payload, payload_size, datetime) VALUES (?, ?, ?, ?, ?)",
            (client, topic, payload, len(payload.encode()), now)
        )
        conn.commit()


def get_sub_history(limit: int = 1000):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM subHistory ORDER BY datetime DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── connectionHistory ──────────────────────────────────────
def log_connection_start(client: str) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO connectionHistory (client, connected_time, mode) VALUES (?, ?, ?)",
            (client, now, "active")
        )
        conn.commit()
        return cursor.lastrowid


def log_connection_end(record_id: int, mode: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            "UPDATE connectionHistory SET disconnected_time = ?, mode = ? WHERE id = ?",
            (now, mode, record_id)
        )
        conn.commit()


def get_connection_history(limit: int = 1000):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM connectionHistory ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── topics ────────────────────────────────────────────────
def get_topics(client: str = None):
    with get_connection() as conn:
        if client:
            rows = conn.execute("SELECT * FROM topics WHERE client = ? ORDER BY id ASC", (client,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM topics ORDER BY client, id ASC").fetchall()
    return [dict(r) for r in rows]


def add_topic(client: str, topic: str) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO topics (client, topic) VALUES (?, ?)", (client, topic)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def delete_topic(topic_id: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
        conn.commit()
    finally:
        conn.close()


# ── appState ───────────────────────────────────────────────
def set_app_state(key: str, value: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO appState (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )
        conn.commit()


def get_app_state(key: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM appState WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


# ── widget_triggers ────────────────────────────────────────
def get_triggers():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM widget_triggers").fetchall()
    return [dict(r) for r in rows]


def add_trigger(source_id: int, target_id: int) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO widget_triggers (source_id, target_id) VALUES (?, ?)",
            (source_id, target_id)
        )
        conn.commit()
        return cursor.lastrowid


def delete_trigger(trigger_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM widget_triggers WHERE id = ?", (trigger_id,))
        conn.commit()


def update_trigger_delay(trigger_id: int, delay_ms: int):
    with get_connection() as conn:
        conn.execute("UPDATE widget_triggers SET delay_ms = ? WHERE id = ?", (delay_ms, trigger_id))
        conn.commit()
