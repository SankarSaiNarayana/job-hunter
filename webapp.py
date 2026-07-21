"""Shared application core — used by BOTH entrypoints:

  app.py        local:  long-running server + background poller (SQLite)
  api/index.py  cloud:  Vercel serverless function + cron (Turso)

Everything stateful lives in the store (jobs, repos, meta like last_poll),
so a serverless instance that dies after each request loses nothing.
"""
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs

import freelance
import matcher
import repos as repos_mod
import sources
import store as store_mod

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
PROFILE_PATH = os.path.join(BASE, "profile.json")

# Hooks the local entrypoint can install; None on serverless.
refresh_hook = None       # called on POST /api/refresh instead of inline poll
notify_hook = None        # called with (title, message) for high matches

_profile_cache = None
_poll_lock = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_profile(cfg):
    """Skill/role profile. Priority: parse the resume file if present
    (local), else the committed profile.json snapshot (what Vercel uses)."""
    global _profile_cache
    if _profile_cache:
        return _profile_cache
    resume_path = os.path.expanduser(cfg.get("resume_path", ""))
    candidates = [resume_path, os.path.join(BASE, "resume.txt")]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                import resume as resume_mod
                text = resume_mod.load_resume_text(path)
                profile = matcher.extract_profile(text, cfg.get("extra_keywords"))
                if profile["skills"]:
                    # Snapshot so serverless deploys can score without pypdf.
                    try:
                        with open(PROFILE_PATH, "w") as f:
                            json.dump(profile, f, indent=1)
                    except OSError:
                        pass  # read-only filesystem (serverless) — fine
                    _profile_cache = profile
                    return profile
            except Exception as e:
                log(f"resume parse failed ({path}): {e}")
    if os.path.exists(PROFILE_PATH):
        with open(PROFILE_PATH) as f:
            _profile_cache = json.load(f)
            return _profile_cache
    _profile_cache = {"skills": [], "roles": [], "years": None}
    return _profile_cache


def get_queries(cfg, profile):
    return (cfg.get("search_queries")
            or matcher.default_queries(profile, cfg.get("focus")))


# ------------------------------------------------------------------- polling

def poll(tasks=("jobs", "gigs", "repos")):
    """One full fetch cycle. Safe to call from a cron, a request handler, or
    the local background thread. Returns a summary dict."""
    with _poll_lock:
        cfg = load_config()
        st = store_mod.get_store()
        profile = load_profile(cfg)
        focus = cfg.get("focus", ["swe", "devops", "aiml"])
        now = now_iso()
        summary = {"new_jobs": 0, "new_gigs": 0, "repos": 0, "errors": {}}

        def score_and_tag(items):
            for j in items:
                score, matched, category = matcher.score_job(profile, j, focus)
                j["score"], j["matched"], j["category"] = score, matched, category
                j["exp_min"], j["exp_max"], j["exp_level"] = \
                    matcher.extract_experience(j)
            return items

        if "jobs" in tasks:
            queries = get_queries(cfg, profile)
            log(f"Polling job sources with queries: {queries}")
            jobs, errors = sources.fetch_all(cfg, queries, log)
            summary["errors"].update(errors)
            new = st.upsert_jobs(score_and_tag(jobs), now)
            summary["new_jobs"] = len(new)
            log(f"Jobs: {len(jobs)} fetched, {len(new)} new")
            _maybe_notify(cfg, new)

        if "gigs" in tasks:
            gig_queries = cfg.get("freelance_queries") or profile["skills"][:4] \
                or ["python", "automation"]
            gigs, gerrors = freelance.fetch_all(cfg, gig_queries, log)
            summary["errors"].update(
                {f"gig:{k}": v for k, v in gerrors.items()})
            new_gigs = st.upsert_jobs(score_and_tag(gigs), now)
            summary["new_gigs"] = len(new_gigs)
            log(f"Gigs: {len(gigs)} fetched, {len(new_gigs)} new")

        # Retire inbox jobs (jobs + gigs) that have sat unactioned for too
        # long, so the inbox never stagnates after days away from the app.
        archive_days = cfg.get("archive_days", 7)
        if archive_days:
            cutoff = (datetime.now(timezone.utc)
                      - timedelta(days=archive_days)).isoformat()
            archived = st.archive_stale(cutoff, now)
            summary["archived"] = archived
            if archived:
                log(f"Archived {archived} stale inbox items "
                    f"(older than {archive_days} days)")

        if "repos" in tasks and _repos_stale(st, cfg):
            try:
                trending = repos_mod.fetch_trending(cfg, log)
                if trending:
                    st.save_repos(trending, now)
                    summary["repos"] = len(trending)
            except Exception as e:
                summary["errors"]["repos"] = f"{type(e).__name__}: {e}"

        st.meta_set("last_poll", now)
        st.meta_set("last_new", str(summary["new_jobs"] + summary["new_gigs"]))
        st.meta_set("errors", json.dumps(summary["errors"]))
        return summary


def _repos_stale(st, cfg):
    fetched = st.meta_get("repos_fetched")
    if not fetched:
        return True
    hours = (cfg.get("repos") or {}).get("refresh_hours", 12)
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(fetched)
        return age.total_seconds() > hours * 3600
    except ValueError:
        return True


def _maybe_notify(cfg, new_jobs):
    if not notify_hook or not cfg.get("notifications", True):
        return
    min_notify = cfg.get("notify_min_score", 8)
    exp_cfg = cfg.get("experience") or {}
    exp_max = exp_cfg.get("max_years")

    def within_exp(j):
        if exp_max is None:
            return True
        mn = j.get("exp_min")
        if mn is None:                       # unknown experience
            return exp_cfg.get("include_unknown", True)
        return mn <= exp_max

    high = [j for j in new_jobs
            if j.get("score", 0) >= min_notify and within_exp(j)]
    if high:
        top = max(high, key=lambda j: j["score"])
        extra = f" (+{len(high) - 1} more)" if len(high) > 1 else ""
        notify_hook("Job Hunter — new match",
                    f"{top['title']} @ {top['company']}{extra}")


# -------------------------------------------------------------------- routes

def route(method, path, q, body, headers):
    """Returns (status_code, payload, content_type). payload may be bytes."""
    st = store_mod.get_store()

    if method == "GET" and path == "/":
        with open(os.path.join(BASE, "dashboard.html"), "rb") as f:
            return 200, f.read(), "text/html; charset=utf-8"

    if method == "GET" and path == "/api/jobs":
        exp_cfg = load_config().get("experience") or {}
        # Query param overrides config; "" means "no ceiling" (show all).
        exp_raw = q.get("exp_max", [None])[0]
        if exp_raw is None:                       # not supplied -> use config
            exp_max = exp_cfg.get("max_years")
        elif exp_raw == "":                       # explicit "Any experience"
            exp_max = None
        else:
            exp_max = int(exp_raw)
        exp_unknown = q.get("exp_unknown", [
            "1" if exp_cfg.get("include_unknown", True) else "0"])[0] != "0"
        rows = st.list_jobs(
            kind=q.get("kind", ["job"])[0],
            stage=q.get("stage", [q.get("state", ["inbox"])[0]])[0],
            category=q.get("category", [""])[0],
            min_score=int(q.get("min_score", ["0"])[0] or 0),
            source=q.get("source", [""])[0],
            search=q.get("q", [""])[0],
            limit=int(q.get("limit", ["200"])[0]),
            exp_max=exp_max,
            exp_floor=int(exp_cfg.get("min_years") or 0),
            exp_unknown=exp_unknown)
        return 200, rows, "application/json"

    if method == "GET" and path == "/api/repos":
        return 200, st.list_repos(), "application/json"

    if method == "GET" and path == "/api/platforms":
        return 200, freelance.PLATFORM_DIRECTORY, "application/json"

    if method == "GET" and path == "/api/status":
        cfg = load_config()
        profile = load_profile(cfg)
        return 200, {
            "profile": {"skills": len(profile["skills"]),
                        "roles": profile["roles"][:5]},
            "queries": get_queries(cfg, profile),
            "focus": cfg.get("focus", ["swe", "devops", "aiml"]),
            "experience": cfg.get("experience") or {},
            "last_poll": st.meta_get("last_poll"),
            "last_new": int(st.meta_get("last_new") or 0),
            "errors": json.loads(st.meta_get("errors") or "{}"),
            "counts": st.counts(),
            "sources": {"job": st.sources_seen("job"),
                        "gig": st.sources_seen("gig")},
            "storage": st.mode,
            "serverless": bool(os.environ.get("VERCEL")),
            "poll_minutes": cfg.get("poll_minutes", 15),
            "fresh_hours": cfg.get("fresh_hours", 24),
            "archive_days": cfg.get("archive_days", 7),
        }, "application/json"

    if method == "GET" and path == "/api/cron":
        # Vercel Cron entrypoint. If CRON_SECRET is set, require it.
        secret = os.environ.get("CRON_SECRET")
        auth = headers.get("authorization") or headers.get("Authorization") or ""
        if secret and auth != f"Bearer {secret}":
            return 401, {"error": "unauthorized"}, "application/json"
        summary = poll()
        return 200, {"ok": True, **summary}, "application/json"

    if method == "POST" and path == "/api/refresh":
        if refresh_hook:            # local: wake the background poller
            refresh_hook()
            return 200, {"ok": True, "mode": "background"}, "application/json"
        summary = poll()            # serverless: poll inline
        return 200, {"ok": True, "mode": "inline", **summary}, "application/json"

    if method == "POST" and path == "/api/stage":
        jid, stage = body.get("id"), body.get("stage") or body.get("state")
        if stage not in store_mod.STAGES:
            return 400, {"error": f"bad stage; use one of {store_mod.STAGES}"}, \
                "application/json"
        st.set_stage(jid, stage, now_iso())
        return 200, {"ok": True}, "application/json"

    if method == "POST" and path == "/api/state":   # legacy alias
        return route("POST", "/api/stage", q, body, headers)

    if method == "POST" and path == "/api/notes":
        st.set_notes(body.get("id"), body.get("notes", ""))
        return 200, {"ok": True}, "application/json"

    return 404, {"error": "not found"}, "application/json"


class HttpMixin:
    """Plugs `route` into any BaseHTTPRequestHandler subclass — used by both
    the local ThreadingHTTPServer and the Vercel python runtime handler."""

    def log_message(self, *a):
        pass

    def _dispatch(self):
        parsed = urlparse(self.path)
        # keep_blank_values so an explicit empty param (e.g. exp_max= meaning
        # "Any experience") reaches the handler instead of silently vanishing.
        q = parse_qs(parsed.query, keep_blank_values=True)
        length = int(self.headers.get("Content-Length") or 0)
        body = {}
        if length:
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                body = {}
        try:
            code, payload, ctype = route(self.command, parsed.path, q, body,
                                         self.headers)
        except Exception as e:
            log(f"route error: {type(e).__name__}: {e}")
            code, payload, ctype = 500, {"error": str(e)}, "application/json"
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = _dispatch
    do_POST = _dispatch
