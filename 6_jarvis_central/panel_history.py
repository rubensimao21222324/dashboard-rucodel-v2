"""Persistent conversations for the unified panel, in the existing Jarvis backup."""
from contextlib import closing
from datetime import datetime, timezone
import secrets
import threading


class PanelHistory:
    def __init__(self, store):
        self.store = store
        self.turn_lock = threading.Lock()
        with closing(store.connect()) as con, con:
            con.execute("CREATE TABLE IF NOT EXISTS central_chats(id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0)")
            con.execute("CREATE TABLE IF NOT EXISTS central_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('user','assistant')),content TEXT NOT NULL,created_at TEXT NOT NULL)")
            con.execute("CREATE INDEX IF NOT EXISTS central_messages_chat ON central_messages(chat_id,id)")

    def list(self):
        with closing(self.store.connect()) as con:
            return [dict(r) for r in con.execute("SELECT * FROM central_chats WHERE archived=0 ORDER BY updated_at DESC,id DESC LIMIT 200")]

    def create(self):
        stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        uid = secrets.token_hex(16)
        with closing(self.store.connect()) as con, con:
            con.execute("INSERT INTO central_chats VALUES(?,?,?,?,0)", (uid, "Nova conversa", stamp, stamp))
        return self.get(uid)

    def get(self, uid):
        with closing(self.store.connect()) as con:
            row = con.execute("SELECT * FROM central_chats WHERE id=? AND archived=0", (uid,)).fetchone()
            if row is None:
                raise ValueError("Essa conversa nao esta disponivel.")
            messages = [dict(r) for r in con.execute("SELECT id,role,content,created_at FROM central_messages WHERE chat_id=? ORDER BY id", (uid,))]
        return {"chat": dict(row), "messages": messages}

    def archive(self, uid):
        with closing(self.store.connect()) as con, con:
            con.execute("UPDATE central_chats SET archived=1 WHERE id=?", (uid,))
        return {"ok": True}

    def answer(self, uid, text, generate):
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 12000:
            raise ValueError("Escreve uma mensagem com ate 12000 caracteres.")
        if not self.turn_lock.acquire(blocking=False):
            raise ValueError("O Jarvis ainda esta a responder. Aguarda um momento.")
        try:
            data = self.get(uid)
            history = [{"role": r["role"], "content": r["content"]} for r in data["messages"][-32:]]
            reply = generate(history + [{"role": "user", "content": text.strip()}])
            if not isinstance(reply, str) or not reply.strip():
                raise ValueError("O modelo devolveu uma resposta vazia. Volta a tentar.")
            stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            title = data["chat"]["title"]
            if not data["messages"]:
                title = " ".join(text.split())[:76]
            with closing(self.store.connect()) as con, con:
                con.execute("INSERT INTO central_messages(chat_id,role,content,created_at) VALUES(?,?,?,?)", (uid, "user", text.strip(), stamp))
                con.execute("INSERT INTO central_messages(chat_id,role,content,created_at) VALUES(?,?,?,?)", (uid, "assistant", reply, stamp))
                con.execute("UPDATE central_chats SET title=?,updated_at=? WHERE id=?", (title, stamp, uid))
            result = self.get(uid)
            result["answer"] = reply
            return result
        finally:
            self.turn_lock.release()
