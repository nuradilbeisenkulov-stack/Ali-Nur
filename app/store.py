"""Private local queue and append-only review feedback in SQLite."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


class QueueStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    ticket TEXT NOT NULL,
                    result TEXT NOT NULL,
                    status TEXT NOT NULL,
                    draft_text TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_demo INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    original_draft TEXT NOT NULL,
                    previous_draft TEXT NOT NULL,
                    edited_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            ''')
        path.chmod(0o600)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        item = dict(row)
        item['ticket'] = json.loads(item['ticket'])
        item['result'] = json.loads(item['result'])
        item['is_demo'] = bool(item['is_demo'])
        return item

    def list(self):
        with self.connect() as conn:
            return [self.decode(row) for row in conn.execute('SELECT * FROM tickets ORDER BY updated_at DESC, id')]

    def add(self, ticket, result, is_demo=False):
        item = {'id': uuid.uuid4().hex, 'ticket': ticket, 'result': result,
                'status': 'new', 'draft_text': result['draft_reply']['text'], 'updated_at': now(), 'is_demo': is_demo}
        with self.lock, self.connect() as conn:
            conn.execute('INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?, ?)', (
                item['id'], json.dumps(ticket, ensure_ascii=False), json.dumps(result, ensure_ascii=False),
                item['status'], item['draft_text'], item['updated_at'], int(is_demo)))
        return item

    def update(self, item_id, action, draft_text=None):
        with self.lock, self.connect() as conn:
            item = self.decode(conn.execute('SELECT * FROM tickets WHERE id = ?', (item_id,)).fetchone())
            if item is None:
                return None
            previous = item['draft_text']
            if draft_text is not None:
                if not draft_text.strip():
                    raise ValueError('Черновик не может быть пустым.')
                item['draft_text'] = draft_text.strip()
            if action == 'edit':
                if draft_text is None:
                    raise ValueError('Для редактирования передайте draft_text.')
                item['status'] = 'reviewed'
            elif action == 'send':
                # This only records a local state transition. No game API or network client exists.
                item['status'] = 'sent'
            elif action == 'escalate':
                item['status'] = 'escalated'
                item['result']['needs_human'] = True
                reason = 'Администратор вручную передал обращение на дополнительное рассмотрение.'
                if reason not in item['result']['reasons']:
                    item['result']['reasons'].append(reason)
            item['updated_at'] = now()
            conn.execute('UPDATE tickets SET result=?, status=?, draft_text=?, updated_at=? WHERE id=?', (
                json.dumps(item['result'], ensure_ascii=False), item['status'], item['draft_text'], item['updated_at'], item_id))
            conn.execute('INSERT INTO feedback (ticket_id,action,original_draft,previous_draft,edited_text,created_at) VALUES (?,?,?,?,?,?)', (
                item_id, action, item['result']['draft_reply']['text'], previous, item['draft_text'], item['updated_at']))
            return item

    def replace_analysis(self, item_id, result):
        with self.lock, self.connect() as conn:
            row = conn.execute('SELECT * FROM tickets WHERE id=?', (item_id,)).fetchone()
            if row is None:
                return None
            item = self.decode(row)
            if item['status'] != 'new':
                raise ValueError('Повторный анализ доступен только до редактирования или завершения обращения.')
            conn.execute('UPDATE tickets SET result=?,draft_text=?,updated_at=? WHERE id=?',
                         (json.dumps(result, ensure_ascii=False), result['draft_reply']['text'], now(), item_id))
            return self.decode(conn.execute('SELECT * FROM tickets WHERE id=?', (item_id,)).fetchone())
