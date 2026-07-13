"""Trending AI repos worth contributing to, via the GitHub Search API.

Two angles, merged and ranked:
  rising      — repos created in the last ~90 days gathering stars fast
                (get in early, small codebase, maintainers responsive).
  contribute  — established AI repos that are actively pushed and explicitly
                ask for help (good-first-issues / help-wanted labels).

No key needed (10 searches/min unauthenticated). Set GITHUB_TOKEN in the env
or config.json 'github_token' for a 30x higher rate limit.
"""
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

from sources import _get_json


def _headers(cfg):
    h = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or cfg.get("github_token") or ""
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _search(cfg, q, sort="stars", per_page=10):
    url = ("https://api.github.com/search/repositories?"
           f"q={urllib.parse.quote(q)}&sort={sort}&order=desc"
           f"&per_page={per_page}")
    return _get_json(url, headers=_headers(cfg)).get("items", [])


def _norm(item, mode):
    return {
        "full_name": item.get("full_name", ""),
        "url": item.get("html_url", ""),
        "description": (item.get("description") or "")[:300],
        "stars": item.get("stargazers_count", 0),
        "forks": item.get("forks_count", 0),
        "open_issues": item.get("open_issues_count", 0),
        "language": item.get("language") or "",
        "topics": (item.get("topics") or [])[:6],
        "mode": mode,
        "created_at": item.get("created_at", ""),
        "pushed_at": item.get("pushed_at", ""),
    }


def fetch_trending(cfg, log):
    rcfg = cfg.get("repos", {})
    topics = rcfg.get("topics", ["llm", "ai-agents", "machine-learning"])
    min_rising = rcfg.get("min_stars_rising", 200)
    now = datetime.now(timezone.utc)
    created_after = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    pushed_after = (now - timedelta(days=14)).strftime("%Y-%m-%d")

    seen, rising, contribute = set(), [], []
    for topic in topics[:3]:
        try:
            for item in _search(
                    cfg, f"topic:{topic} created:>{created_after} "
                         f"stars:>{min_rising}", per_page=8):
                if item["full_name"] not in seen:
                    seen.add(item["full_name"])
                    rising.append(_norm(item, "rising"))
        except Exception as e:
            log(f"  repos rising/{topic}: FAILED ({type(e).__name__}: {e})")
        try:
            for item in _search(
                    cfg, f"topic:{topic} good-first-issues:>3 "
                         f"pushed:>{pushed_after} stars:>1000", per_page=8):
                if item["full_name"] not in seen:
                    seen.add(item["full_name"])
                    contribute.append(_norm(item, "contribute"))
        except Exception as e:
            log(f"  repos contribute/{topic}: FAILED ({type(e).__name__}: {e})")

    # Rank rising by star velocity (stars per day of life), contribute by stars.
    def velocity(r):
        try:
            created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
            days = max(1, (now - created).days)
        except Exception:
            days = 90
        return r["stars"] / days

    rising.sort(key=velocity, reverse=True)
    contribute.sort(key=lambda r: r["stars"], reverse=True)
    out = rising[:8] + contribute[:8]
    log(f"  repos: {len(rising)} rising, {len(contribute)} contribute-friendly")
    return out
