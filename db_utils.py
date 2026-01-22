import sqlite3
import datetime
from typing import Any, Dict, List

DB_FILE = "pulse.db"

def init_db() -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
        cur = conn.execute("SELECT COUNT(*) FROM settings")
        if cur.fetchone()[0] == 0:
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("auto_run", "0"))
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("interval", "60"))

        conn.execute('CREATE TABLE IF NOT EXISTS test_urls (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE)')
        cur = conn.execute('SELECT COUNT(*) FROM test_urls')
        if cur.fetchone()[0] == 0:
            conn.execute('INSERT INTO test_urls (url) VALUES (?)', ("http://cp.cloudflare.com",))

        # Groups with sort_order
        conn.execute('CREATE TABLE IF NOT EXISTS ui_groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sort_order INTEGER DEFAULT 0)')
        conn.execute('INSERT OR IGNORE INTO ui_groups (name, sort_order) VALUES (?, ?)', ("General", 0))

        # Monitors with sort_order
        conn.execute('''CREATE TABLE IF NOT EXISTS monitor_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT, 
            link TEXT, 
            group_name TEXT DEFAULT 'General',
            sort_order INTEGER DEFAULT 0
        )''')
        
        conn.execute('CREATE TABLE IF NOT EXISTS proxies (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)')
        
        # История с авто-таймстемпом
        conn.execute('''CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            proxy_id INTEGER, 
            status INTEGER, 
            latency INTEGER, 
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
            FOREIGN KEY(proxy_id) REFERENCES proxies(id)
        )''')
        
        conn.execute('CREATE INDEX IF NOT EXISTS idx_proxy ON history (proxy_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_time ON history (timestamp)')

# --- SETTINGS ---
def get_settings() -> dict:
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute('SELECT key, value FROM settings')
        data = {k: v for k, v in cur.fetchall()}
        return { "auto_run": bool(int(data.get("auto_run", "0"))), "interval": int(data.get("interval", "60")) }

def save_settings(auto_run: bool, interval: int) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ("auto_run", str(int(auto_run))))
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ("interval", str(interval)))

# --- TEST URLS ---
def get_test_urls() -> List[str]:
    with sqlite3.connect(DB_FILE) as conn: return [r[0] for r in conn.execute('SELECT url FROM test_urls').fetchall()]

def save_test_urls(urls: List[str]) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('DELETE FROM test_urls')
        for url in urls: 
            if url.strip(): conn.execute('INSERT INTO test_urls (url) VALUES (?)', (url.strip(),))

# --- SORTING LOGIC ---
def update_group_order(names: List[str]) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        for idx, name in enumerate(names):
            conn.execute('UPDATE ui_groups SET sort_order = ? WHERE name = ?', (idx, name))

# --- GROUPS ---
def get_groups() -> List[str]:
    with sqlite3.connect(DB_FILE) as conn:
        return [r[0] for r in conn.execute('SELECT name FROM ui_groups ORDER BY sort_order ASC, id ASC').fetchall()]

def add_group(name: str) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        max_order = conn.execute('SELECT MAX(sort_order) FROM ui_groups').fetchone()[0] or 0
        conn.execute('INSERT OR IGNORE INTO ui_groups (name, sort_order) VALUES (?, ?)', (name, max_order + 1))

def delete_group(name: str) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE monitor_configs SET group_name='General' WHERE group_name=?", (name,))
        conn.execute('DELETE FROM ui_groups WHERE name=?', (name,))

# --- MONITORS ---
def get_monitor_configs() -> List[dict]:
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT * FROM monitor_configs ORDER BY sort_order ASC, id ASC').fetchall()
        return [dict(r) for r in rows]

def save_monitor_configs(configs: List[dict]) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('DELETE FROM monitor_configs')
        existing_groups = {r[0] for r in conn.execute('SELECT name FROM ui_groups').fetchall()}
        
        for idx, c in enumerate(configs):
            g = c.get('group', 'General')
            if g not in existing_groups:
                conn.execute('INSERT OR IGNORE INTO ui_groups (name) VALUES (?)', (g,))
                existing_groups.add(g)
            
            conn.execute(
                'INSERT INTO monitor_configs (name, link, group_name, sort_order) VALUES (?, ?, ?, ?)',
                (c.get('name'), c.get('link'), g, idx)
            )

# --- HISTORY ---
def save_check_result(proxy_unique_name: str, status: bool, latency: int) -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM history WHERE timestamp < datetime('now', '-30 days')")
        cur = conn.execute('SELECT id FROM proxies WHERE name = ?', (proxy_unique_name,))
        row = cur.fetchone()
        if row: pid = row[0]
        else:
            cur = conn.execute('INSERT INTO proxies (name) VALUES (?)', (proxy_unique_name,))
            pid = cur.lastrowid
        
        # Timestamp ставится базой автоматически
        conn.execute('INSERT INTO history (proxy_id, status, latency) VALUES (?, ?, ?)', (pid, 1 if status else 0, latency))

def get_proxy_stats(proxy_unique_name: str) -> dict:
    stats = {"1d": 0, "30d": 0, "1y": 0, "history": [], "history_ts": []}
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute('SELECT id FROM proxies WHERE name = ?', (proxy_unique_name,))
        row = cur.fetchone()
        if not row: return stats
        pid = row[0]
        
        # Получаем статус и время (в секундах)
        rows = conn.execute("SELECT status, strftime('%s', timestamp) FROM history WHERE proxy_id=? ORDER BY id DESC LIMIT 50", (pid,)).fetchall()
        
        if rows:
            rev_rows = rows[::-1]
            stats["history"] = [r[0] for r in rev_rows]
            stats["history_ts"] = [int(r[1]) if r[1] else 0 for r in rev_rows]

        for k, d in [("1d", "-1 day"), ("30d", "-30 days"), ("1y", "-365 days")]:
            val = conn.execute(f"SELECT AVG(status) FROM history WHERE proxy_id=? AND timestamp >= datetime('now', '{d}')", (pid,)).fetchone()[0]
            stats[k] = int(val * 100) if val is not None else 100
    return stats

def clear_all_history() -> None:
    with sqlite3.connect(DB_FILE) as conn: conn.execute('DELETE FROM history')