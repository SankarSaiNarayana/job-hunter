"""Freelance gig fetchers — a separate section from jobs (kind='gig').

Solid source:
  freelancer   — Freelancer.com official public projects API (no key).

Best-effort sources (feeds that platforms throttle — they fail gracefully
and never break a poll):
  truelancer   — HTML search page, regex-parsed.

Platforms with no public feed at all (Upwork retired its RSS in 2024;
Fiverr, Toptal, Contra, Malt, Braintrust, Arc.dev, Gun.io, Codeable,
Workana, PeoplePerHour, Guru have none) are in
PLATFORM_DIRECTORY below and rendered as one-click links on the dashboard's
Freelance tab, so nothing renowned is left out.
"""
import re
import urllib.parse

from sources import _get, _get_json, _job, _strip_html, run_fetchers

# Globally renowned platforms — shown as a directory in the Freelance tab.
PLATFORM_DIRECTORY = {
    "freelance": [
        {"name": "Upwork", "url": "https://www.upwork.com/nx/search/jobs/", "note": "World's largest freelance marketplace"},
        {"name": "Fiverr", "url": "https://www.fiverr.com/categories/programming-tech", "note": "Sell fixed-price gigs (programming & tech)"},
        {"name": "Freelancer.com", "url": "https://www.freelancer.com/jobs", "note": "Project bidding marketplace"},
        {"name": "Toptal", "url": "https://www.toptal.com/talent/apply", "note": "Elite vetted network — top rates"},
        {"name": "Braintrust", "url": "https://app.usebraintrust.com/auth/signup/", "note": "0% fee talent network"},
        {"name": "Arc.dev", "url": "https://arc.dev/for-developers", "note": "Vetted remote developer network"},
        {"name": "Contra", "url": "https://contra.com/opportunities", "note": "Commission-free independent work"},
        {"name": "Gun.io", "url": "https://www.gun.io/", "note": "Freelance network for developers"},
        {"name": "Turing", "url": "https://www.turing.com/jobs", "note": "Long-term remote engineering jobs"},
        {"name": "PeoplePerHour", "url": "https://www.peopleperhour.com/freelance-jobs", "note": "Hourly & project work (UK-centric)"},
        {"name": "Guru", "url": "https://www.guru.com/d/jobs/", "note": "Project marketplace"},
        {"name": "Malt", "url": "https://www.malt.com/", "note": "Europe's leading freelance platform"},
        {"name": "Workana", "url": "https://www.workana.com/en/jobs", "note": "LatAm + global projects"},
        {"name": "Truelancer", "url": "https://www.truelancer.com/freelance-jobs", "note": "India-centric marketplace"},
        {"name": "Codeable", "url": "https://www.codeable.io/developers/", "note": "WordPress expert network"},
        {"name": "99designs", "url": "https://99designs.com/", "note": "Design contests & projects"},
    ],
    "jobs": [
        {"name": "Indeed", "url": "https://www.indeed.com/", "note": "Covered via jsearch key"},
        {"name": "Glassdoor", "url": "https://www.glassdoor.com/Job/index.htm", "note": "Covered via jsearch key"},
        {"name": "Wellfound (AngelList)", "url": "https://wellfound.com/jobs", "note": "Startup jobs — login required"},
        {"name": "Y Combinator", "url": "https://www.workatastartup.com/", "note": "YC startup jobs"},
        {"name": "Dice", "url": "https://www.dice.com/jobs", "note": "US tech jobs"},
        {"name": "Monster", "url": "https://www.monster.com/jobs/", "note": ""},
        {"name": "ZipRecruiter", "url": "https://www.ziprecruiter.com/jobs-search", "note": ""},
        {"name": "Hired", "url": "https://hired.com/", "note": "Reverse marketplace"},
        {"name": "Otta / Welcome to the Jungle", "url": "https://app.welcometothejungle.com/", "note": "Curated tech jobs"},
        {"name": "Instahyre", "url": "https://www.instahyre.com/", "note": "India — top product companies"},
        {"name": "Cutshort", "url": "https://cutshort.io/jobs", "note": "India tech jobs"},
        {"name": "Hirist", "url": "https://www.hirist.tech/", "note": "India tech jobs"},
        {"name": "Internshala", "url": "https://internshala.com/jobs/", "note": "India internships & fresher jobs"},
    ],
}


def fetch_freelancer(cfg, queries):
    """Freelancer.com official public API — the most reliable gig feed."""
    gigs = []
    for q in queries[:3]:
        url = ("https://www.freelancer.com/api/projects/0.1/projects/active/"
               f"?query={urllib.parse.quote(q)}&limit=30&compact=true"
               "&full_description=false&job_details=true")
        data = _get_json(url)
        for p in (data.get("result") or {}).get("projects", []):
            budget = p.get("budget") or {}
            currency = (p.get("currency") or {}).get("code", "")
            lo, hi = budget.get("minimum"), budget.get("maximum")
            budget_s = ""
            if lo:
                budget_s = f"Budget: {currency} {lo:g}" + (f"–{hi:g}" if hi else "+")
            skills = [j.get("name") for j in (p.get("jobs") or [])]
            gigs.append(_job(
                "freelancer", p.get("title"), "Freelancer.com",
                "Remote", "https://www.freelancer.com/projects/" + (p.get("seo_url") or ""),
                (budget_s + ". " if budget_s else "") + (p.get("preview_description") or ""),
                skills, str(p.get("time_submitted", ""))))
    return gigs


def fetch_truelancer(cfg, queries):
    """Truelancer HTML search — best-effort regex parse."""
    gigs = []
    for q in queries[:1]:
        raw = _get("https://www.truelancer.com/freelance-jobs?q="
                   + urllib.parse.quote(q), retries=0)
        for m in re.finditer(
                r'href="(https://www\.truelancer\.com/project/[^"]+)"[^>]*>\s*([^<]{10,120})',
                raw):
            gigs.append(_job(
                "truelancer", _strip_html(m.group(2)), "Truelancer",
                "Remote", m.group(1), "", [q], ""))
    return gigs


FETCHERS = {
    "freelancer": fetch_freelancer,
    "truelancer": fetch_truelancer,
}


def fetch_all(cfg, queries, log):
    enabled = cfg.get("freelance_sources", list(FETCHERS))
    fetchers = {n: FETCHERS[n] for n in enabled if n in FETCHERS}
    gigs, errors = run_fetchers(fetchers, cfg, queries, log, label="gig:")
    for g in gigs:
        g["kind"] = "gig"
    return gigs, errors
