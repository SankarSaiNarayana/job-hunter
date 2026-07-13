"""Storage layer — append-only job history with two interchangeable backends.

Local:  SQLite (data.db) — zero setup, used when you run `python3 app.py`.
Cloud:  Turso / libSQL over HTTP — used automatically when the env vars
        TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set. This is what makes
        the app deployable on Vercel-style platforms, whose filesystems are
        read-only and wiped between invocations.

Design guarantees:
  * INSERT-only for discovered jobs — a poll can never delete or overwrite
    what you already have. Re-seen jobs only get their `last_seen` bumped.
  * Dedup happens on BOTH the url hash (id) and a title+company fingerprint,
    so the same role arriving from two boards doesn't show up twice.
  * Your pipeline stages (applied / interviewing / offer ...) live on the row
    and are never touched by polling.
"""
import hashlib
import json
import os
import re
import sqlite3
import threading
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data.db")

STAGES = ("new", "seen", "applied", "interviewing", "offer", "rejected",
          "hidden", "archived")

_JOB_COLUMNS = [
    # (name, type/default) — used both for CREATE TABLE and for migrating
    # older databases forward with ALTER TABLE.
    ("id", "TEXT PRIMARY KEY"),
    ("kind", "TEXT DEFAULT 'job'"),          # 'job' | 'gig' (freelance)
    ("source", "TEXT"),
    ("title", "TEXT"),
    ("company", "TEXT"),
    ("location", "TEXT"),
    ("url", "TEXT"),
    ("description", "TEXT"),
    ("tags", "TEXT"),
    ("category", "TEXT DEFAULT ''"),         # 'swe' | 'devops' | 'aiml' | 'other'
    ("posted_at", "TEXT"),
    ("fetched_at", "TEXT"),
    ("first_seen", "TEXT"),
    ("last_seen", "TEXT"),
    ("score", "INTEGER"),
    ("matched", "TEXT"),
    ("state", "TEXT DEFAULT 'new'"),         # legacy column, mirrored from stage
    ("stage", "TEXT DEFAULT 'new'"),
    ("stage_updated", "TEXT"),
    ("notes", "TEXT DEFAULT ''"),
    ("fingerprint", "TEXT"),
]


def fingerprint(title, company):
    """Stable cross-source identity: normalized title + company."""
    key = re.sub(r"[^a-z0-9]+", " ", f"{title} {company}".lower()).strip()
    if not key:
        return ""
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def job_id(url):
    return hashlib.sha1(url.encode()).hexdigest()[:16]


# --------------------------------------------------------------- backends

class SqliteBackend:
    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()

    def execute(self, sql, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            self.conn.commit()
            return rows

    def execute_many(self, statements):
        with self.lock:
            for sql, params in statements:
                self.conn.execute(sql, params)
            self.conn.commit()


class TursoBackend:
    """Minimal libSQL-over-HTTP client (v2/pipeline) — stdlib only."""

    def __init__(self, url, token):
        url = url.replace("libsql://", "https://").rstrip("/")
        self.url = url + "/v2/pipeline"
        self.token = token

    @staticmethod
    def _arg(v):
        if v is None:
            return {"type": "null", "value": None}
        if isinstance(v, bool):
            return {"type": "integer", "value": str(int(v))}
        if isinstance(v, int):
            return {"type": "integer", "value": str(v)}
        if isinstance(v, float):
            return {"type": "float", "value": v}
        return {"type": "text", "value": str(v)}

    @staticmethod
    def _val(cell):
        t = cell.get("type")
        if t == "null":
            return None
        if t == "integer":
            return int(cell["value"])
        if t == "float":
            return float(cell["value"])
        return cell.get("value")

    def _pipeline(self, statements):
        reqs = [{"type": "execute",
                 "stmt": {"sql": sql, "args": [self._arg(p) for p in params]}}
                for sql, params in statements]
        reqs.append({"type": "close"})
        body = json.dumps({"requests": reqs}).encode()
        req = urllib.request.Request(self.url, data=body, headers={
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.loads(r.read().decode())
        results = []
        for res in out.get("results", []):
            if res.get("type") == "error":
                raise RuntimeError(f"turso: {res.get('error', {}).get('message')}")
            resp = res.get("response", {})
            if resp.get("type") != "execute":
                continue
            result = resp.get("result", {})
            cols = [c.get("name") for c in result.get("cols", [])]
            rows = [dict(zip(cols, (self._val(c) for c in row)))
                    for row in result.get("rows", [])]
            results.append(rows)
        return results

    def execute(self, sql, params=()):
        out = self._pipeline([(sql, list(params))])
        return out[0] if out else []

    def execute_many(self, statements):
        # Turso pipelines are atomic-ish and much faster than N round trips.
        CHUNK = 40
        statements = list(statements)
        for i in range(0, len(statements), CHUNK):
            self._pipeline(statements[i:i + CHUNK])


# ------------------------------------------------------------------ store

class Store:
    def __init__(self):
        turso_url = os.environ.get("TURSO_DATABASE_URL")
        turso_token = os.environ.get("TURSO_AUTH_TOKEN")
        if turso_url and turso_token:
            self.backend = TursoBackend(turso_url, turso_token)
            self.mode = "turso"
        else:
            self.backend = SqliteBackend()
            self.mode = "sqlite"
        self._ensure_schema()

    # -- schema / migration -------------------------------------------------

    def _ensure_schema(self):
        cols = ", ".join(f"{n} {t}" for n, t in _JOB_COLUMNS)
        self.backend.execute(f"CREATE TABLE IF NOT EXISTS jobs ({cols})")
        self.backend.execute("""
            CREATE TABLE IF NOT EXISTS repos (
                full_name TEXT PRIMARY KEY, url TEXT, description TEXT,
                stars INTEGER, forks INTEGER, open_issues INTEGER,
                language TEXT, topics TEXT, mode TEXT,
                created_at TEXT, pushed_at TEXT, fetched_at TEXT, rank INTEGER
            )""")
        self.backend.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        # Migrate pre-existing databases forward: add any column that's missing.
        for name, decl in _JOB_COLUMNS:
            if name == "id":
                continue
            try:
                self.backend.execute(f"ALTER TABLE jobs ADD COLUMN {name} {decl}")
            except Exception:
                pass  # column already exists
        # Backfill new columns on legacy rows — never destructive.
        self.backend.execute(
            "UPDATE jobs SET stage = state WHERE (stage IS NULL OR stage = '' "
            "OR stage = 'new') AND state IS NOT NULL AND state != 'new'")
        self.backend.execute(
            "UPDATE jobs SET stage = 'new' WHERE stage IS NULL OR stage = ''")
        self.backend.execute(
            "UPDATE jobs SET kind = 'job' WHERE kind IS NULL OR kind = ''")
        self.backend.execute(
            "UPDATE jobs SET first_seen = fetched_at WHERE first_seen IS NULL")
        self.backend.execute(
            "UPDATE jobs SET last_seen = fetched_at WHERE last_seen IS NULL")
        self._backfill_fingerprints()

    def _backfill_fingerprints(self):
        rows = self.backend.execute(
            "SELECT id, title, company FROM jobs "
            "WHERE fingerprint IS NULL OR fingerprint = '' LIMIT 500")
        if not rows:
            return
        stmts = [("UPDATE jobs SET fingerprint=? WHERE id=?",
                  [fingerprint(r["title"] or "", r["company"] or ""), r["id"]])
                 for r in rows]
        self.backend.execute_many(stmts)

    # -- meta ----------------------------------------------------------------

    def meta_get(self, key, default=None):
        rows = self.backend.execute("SELECT value FROM meta WHERE key=?", [key])
        return rows[0]["value"] if rows else default

    def meta_set(self, key, value):
        self.backend.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", [key, value])

    # -- jobs ----------------------------------------------------------------

    def upsert_jobs(self, jobs, now):
        """Insert unseen jobs; bump last_seen on re-seen ones. Never deletes,
        never touches stage/notes. Returns the list of newly inserted jobs."""
        existing = self.backend.execute("SELECT id, fingerprint FROM jobs")
        ids = {r["id"] for r in existing}
        fps = {r["fingerprint"] for r in existing if r["fingerprint"]}

        inserts, touch_ids, new_jobs = [], [], []
        for j in jobs:
            jid = job_id(j["url"])
            fp = fingerprint(j["title"], j["company"])
            if jid in ids:
                touch_ids.append(jid)
                continue
            if fp and fp in fps:
                continue  # same role already known from another board
            ids.add(jid)
            if fp:
                fps.add(fp)
            inserts.append((
                "INSERT INTO jobs (id, kind, source, title, company, location, "
                "url, description, tags, category, posted_at, fetched_at, "
                "first_seen, last_seen, score, matched, state, stage, "
                "stage_updated, notes, fingerprint) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new','new',?,'',?)",
                [jid, j.get("kind", "job"), j["source"], j["title"], j["company"],
                 j["location"], j["url"], j["description"],
                 json.dumps(j.get("tags") or []), j.get("category", "other"),
                 j.get("posted_at", ""), now, now, now,
                 j.get("score", 0), json.dumps(j.get("matched") or []), now, fp]))
            new_jobs.append(j)

        if inserts:
            self.backend.execute_many(inserts)
        for i in range(0, len(touch_ids), 200):
            chunk = touch_ids[i:i + 200]
            marks = ",".join("?" * len(chunk))
            self.backend.execute(
                f"UPDATE jobs SET last_seen=? WHERE id IN ({marks})",
                [now] + chunk)
        return new_jobs

    def list_jobs(self, kind="job", stage="inbox", category="", min_score=0,
                  source="", search="", limit=200):
        where, params = ["kind = ?"], [kind]
        if stage == "inbox":
            where.append("stage IN ('new','seen')")
        elif stage != "all":
            where.append("stage = ?")
            params.append(stage)
        if category:
            where.append("category = ?")
            params.append(category)
        if min_score:
            where.append("score >= ?")
            params.append(int(min_score))
        if source:
            where.append("source = ?")
            params.append(source)
        if search:
            where.append("(title LIKE ? OR company LIKE ? OR description LIKE ?)")
            needle = f"%{search}%"
            params += [needle, needle, needle]
        sql = ("SELECT * FROM jobs WHERE " + " AND ".join(where) +
               " ORDER BY score DESC, first_seen DESC LIMIT ?")
        params.append(int(limit))
        rows = self.backend.execute(sql, params)
        for d in rows:
            d["tags"] = json.loads(d.get("tags") or "[]")
            d["matched"] = json.loads(d.get("matched") or "[]")
            d["description"] = (d.get("description") or "")[:400]
        return rows

    def archive_stale(self, cutoff_iso, now):
        """Move inbox jobs first seen before cutoff to 'archived' so the inbox
        stays fresh after days of not running the app. Tracked stages
        (applied/interviewing/...) and user-hidden jobs are never touched."""
        rows = self.backend.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE stage IN ('new','seen') "
            "AND first_seen < ?", [cutoff_iso])
        n = rows[0]["c"] if rows else 0
        if n:
            self.backend.execute(
                "UPDATE jobs SET stage='archived', state='hidden', "
                "stage_updated=? WHERE stage IN ('new','seen') "
                "AND first_seen < ?", [now, cutoff_iso])
        return n

    def set_stage(self, jid, stage, now):
        if stage not in STAGES:
            raise ValueError(f"bad stage: {stage}")
        legacy = ("hidden" if stage == "archived" else
                  stage if stage in ("new", "seen", "applied", "hidden")
                  else "applied")
        self.backend.execute(
            "UPDATE jobs SET stage=?, state=?, stage_updated=? WHERE id=?",
            [stage, legacy, now, jid])

    def set_notes(self, jid, notes):
        self.backend.execute(
            "UPDATE jobs SET notes=? WHERE id=?", [(notes or "")[:2000], jid])

    def counts(self):
        rows = self.backend.execute(
            "SELECT kind, stage, COUNT(*) AS c FROM jobs GROUP BY kind, stage")
        out = {}
        for r in rows:
            out.setdefault(r["kind"] or "job", {})[r["stage"] or "new"] = r["c"]
        return out

    def sources_seen(self, kind="job"):
        rows = self.backend.execute(
            "SELECT DISTINCT source FROM jobs WHERE kind=? ORDER BY source", [kind])
        return [r["source"] for r in rows if r["source"]]

    # -- repos ---------------------------------------------------------------

    def save_repos(self, repos, now):
        self.backend.execute("DELETE FROM repos")
        stmts = [(
            "INSERT INTO repos (full_name, url, description, stars, forks, "
            "open_issues, language, topics, mode, created_at, pushed_at, "
            "fetched_at, rank) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [r["full_name"], r["url"], r["description"], r["stars"], r["forks"],
             r["open_issues"], r["language"], json.dumps(r["topics"]),
             r["mode"], r["created_at"], r["pushed_at"], now, i])
            for i, r in enumerate(repos)]
        if stmts:
            self.backend.execute_many(stmts)
        self.meta_set("repos_fetched", now)

    def list_repos(self):
        rows = self.backend.execute("SELECT * FROM repos ORDER BY rank")
        for r in rows:
            r["topics"] = json.loads(r.get("topics") or "[]")
        return rows


_store = None
_store_lock = threading.Lock()


def get_store():
    global _store
    with _store_lock:
        if _store is None:
            _store = Store()
        return _store
