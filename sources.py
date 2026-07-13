"""Job fetchers. Each returns a list of normalized job dicts:
{source, title, company, location, url, description, tags, posted_at}

No-key sources:
  remotive, remoteok, arbeitnow, weworkremotely, jobicy, himalayas,
  workingnomads, themuse, hnhiring (Hacker News "Who is hiring"),
  greenhouse + lever (official public company-board APIs),
  linkedin (public guest feed, best-effort), naukri (best-effort).

Optional key sources (free tiers, keys via config.json or env vars):
  adzuna, jsearch (RapidAPI — LinkedIn/Indeed/Glassdoor/Naukri via
  Google-for-Jobs), findwork, jooble, usajobs.

Boards with no public feed at all (Indeed, Glassdoor, Wellfound, Dice,
Monster, ZipRecruiter, Instahyre, Cutshort...) are covered indirectly by
jsearch and listed in the dashboard's platform directory.

All fetchers run concurrently and fail independently — one broken source
never kills a poll. The HTTP layer retries with backoff and rotates
user agents, and supports gzip.
"""
import gzip
import html
import json
import os
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CTX = _ssl_context()
# Escape hatch for corporate proxies that MITM TLS (self-signed cert in chain).
# Only set JOBHUNTER_INSECURE_SSL=1 if you understand the tradeoff.
if os.environ.get("JOBHUNTER_INSECURE_SSL") == "1":
    _CTX = ssl._create_unverified_context()


def _get(url, headers=None, timeout=25, retries=2, method="GET", data=None):
    """HTTP fetch with retries, exponential backoff + jitter, UA rotation,
    and transparent gzip — the workhorse behind every scraper here."""
    last_err = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "User-Agent": UAS[attempt % len(UAS)],
            "Accept-Encoding": "gzip",
            "Accept": "*/*",
            **(headers or {}),
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (401, 403, 404):
                raise  # retrying won't help
        except Exception as e:
            last_err = e
        if attempt < retries:
            time.sleep((1.5 ** attempt) + random.uniform(0, 0.7))
    raise last_err


def _get_json(url, headers=None, timeout=25, **kw):
    return json.loads(_get(url, headers=headers, timeout=timeout, **kw))


def _strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _job(source, title, company, location, url, description="", tags=None,
         posted_at=""):
    return {
        "source": source,
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "url": (url or "").strip(),
        "description": _strip_html(description)[:2000],
        "tags": [t for t in (tags or []) if t],
        "posted_at": str(posted_at or ""),
    }


def _cfg_key(cfg, section, key, env):
    """Key from config.json, overridable by env var (for Vercel deploys)."""
    return os.environ.get(env) or (cfg.get(section) or {}).get(key) or ""


# ---------------------------------------------------------------- no-key APIs

def fetch_remotive(cfg, queries):
    jobs = []
    for q in queries[:2]:
        url = f"https://remotive.com/api/remote-jobs?search={urllib.parse.quote(q)}&limit=50"
        for j in _get_json(url).get("jobs", []):
            jobs.append(_job(
                "remotive", j.get("title"), j.get("company_name"),
                j.get("candidate_required_location", "Remote"),
                j.get("url"), j.get("description"), j.get("tags"),
                j.get("publication_date", "")))
    return jobs


def fetch_remoteok(cfg, queries):
    data = _get_json("https://remoteok.com/api")
    jobs = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue  # first element is a legal notice
        jobs.append(_job(
            "remoteok", j.get("position"), j.get("company"),
            j.get("location", "Remote"), j.get("url"),
            j.get("description"), j.get("tags"), j.get("date", "")))
    return jobs


def fetch_arbeitnow(cfg, queries):
    data = _get_json("https://www.arbeitnow.com/api/job-board-api")
    jobs = []
    for j in data.get("data", []):
        loc = j.get("location", "")
        if j.get("remote"):
            loc = (loc + " (Remote)").strip()
        jobs.append(_job(
            "arbeitnow", j.get("title"), j.get("company_name"), loc,
            j.get("url"), j.get("description"), j.get("tags"),
            str(j.get("created_at", ""))))
    return jobs


def fetch_weworkremotely(cfg, queries):
    raw = _get("https://weworkremotely.com/remote-jobs.rss")
    root = ET.fromstring(raw)
    jobs = []
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        company = ""
        if ":" in title:
            company, title = title.split(":", 1)
        jobs.append(_job(
            "weworkremotely", title, company,
            item.findtext("region") or "Remote",
            item.findtext("link"), item.findtext("description"),
            [c.text for c in item.findall("category") if c.text],
            item.findtext("pubDate") or ""))
    return jobs


def fetch_jobicy(cfg, queries):
    jobs = []
    for q in queries[:2]:
        url = (f"https://jobicy.com/api/v2/remote-jobs?count=50"
               f"&tag={urllib.parse.quote(q)}")
        for j in _get_json(url).get("jobs", []):
            jobs.append(_job(
                "jobicy", j.get("jobTitle"), j.get("companyName"),
                j.get("jobGeo", "Remote"), j.get("url"),
                j.get("jobExcerpt") or j.get("jobDescription"),
                (j.get("jobIndustry") or []) + (j.get("jobType") or []),
                j.get("pubDate", "")))
    return jobs


def fetch_himalayas(cfg, queries):
    data = _get_json("https://himalayas.app/jobs/api?limit=60")
    jobs = []
    for j in data.get("jobs", []):
        url = j.get("applicationLink") or j.get("guid") or ""
        locs = ", ".join(j.get("locationRestrictions") or []) or "Remote"
        posted = j.get("pubDate")
        if isinstance(posted, (int, float)):
            posted = time.strftime("%Y-%m-%d", time.gmtime(posted))
        jobs.append(_job(
            "himalayas", j.get("title"), j.get("companyName"), locs, url,
            j.get("excerpt") or j.get("description"),
            (j.get("categories") or []) + (j.get("seniority") or []),
            posted or ""))
    return jobs


def fetch_workingnomads(cfg, queries):
    data = _get_json("https://www.workingnomads.com/api/exposed_jobs/")
    jobs = []
    for j in data:
        jobs.append(_job(
            "workingnomads", j.get("title"), j.get("company_name"),
            j.get("location") or "Remote", j.get("url"),
            j.get("description"),
            [t for t in (j.get("tags") or "").split(",") if t],
            j.get("pub_date", "")))
    return jobs


def fetch_themuse(cfg, queries):
    cats = ["Software Engineering", "Data Science", "IT",
            "Data and Analytics"]
    params = "&".join("category=" + urllib.parse.quote(c) for c in cats)
    jobs = []
    for page in (1, 2):
        data = _get_json(
            f"https://www.themuse.com/api/public/jobs?page={page}&{params}")
        for j in data.get("results", []):
            jobs.append(_job(
                "themuse", j.get("name"), (j.get("company") or {}).get("name"),
                ", ".join(l.get("name", "") for l in (j.get("locations") or [])[:2]),
                (j.get("refs") or {}).get("landing_page"),
                j.get("contents"),
                [c.get("name") for c in (j.get("categories") or [])] +
                [l.get("name") for l in (j.get("levels") or [])],
                j.get("publication_date", "")))
    return jobs


def fetch_hnhiring(cfg, queries):
    """Hacker News monthly 'Ask HN: Who is hiring?' thread via Algolia."""
    found = _get_json(
        "https://hn.algolia.com/api/v1/search_by_date?"
        "query=%22who%20is%20hiring%22&tags=story,author_whoishiring"
        "&hitsPerPage=1")
    hits = found.get("hits", [])
    if not hits:
        return []
    story_id = hits[0]["objectID"]
    month = hits[0].get("title", "").replace("Ask HN: Who is hiring? ", "")
    data = _get_json(
        f"https://hn.algolia.com/api/v1/search_by_date?"
        f"tags=comment,story_{story_id}&hitsPerPage=150")
    relevance = ["engineer", "developer", "devops", "sre", " ml ", " ai ",
                 "machine learning", "backend", "frontend", "full stack",
                 "fullstack", "software", "llm"]
    jobs = []
    for c in data.get("hits", []):
        text = _strip_html(c.get("comment_text") or "")
        if not text or not any(k in " " + text.lower() + " " for k in relevance):
            continue
        # Convention: "Company | Role | Location | ..." on the first line
        fields = [f.strip() for f in text.split("|")]
        company = fields[0][:60] if fields else ""
        title = fields[1][:100] if len(fields) > 1 else "Engineering role"
        location = fields[2][:60] if len(fields) > 2 else ""
        jobs.append(_job(
            "hnhiring", title, company, location,
            f"https://news.ycombinator.com/item?id={c['objectID']}",
            text, ["hn", month], c.get("created_at", "")))
    return jobs


# Company boards list every open role (sales, legal, ...) — keep only titles
# relevant to the SWE / DevOps / AI-ML focus.
_RELEVANT_TITLE = re.compile(
    r"engineer|developer|devops|sre|software|machine.?learning|\bml\b|\bai\b|"
    r"data|infrastructure|platform|cloud|backend|back.?end|frontend|"
    r"front.?end|full.?stack|reliab|security|research", re.I)


def fetch_greenhouse(cfg, queries):
    """Official public Greenhouse board API — configure company slugs in
    config.json 'greenhouse_boards' (e.g. anthropic, stripe, databricks)."""
    jobs = []
    for board in cfg.get("greenhouse_boards", [])[:12]:
        try:
            data = _get_json(
                f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
                retries=0)
        except Exception:
            continue  # board slug doesn't exist / moved — skip quietly
        for j in data.get("jobs", []):
            if not _RELEVANT_TITLE.search(j.get("title") or ""):
                continue
            jobs.append(_job(
                "greenhouse", j.get("title"), board.title(),
                (j.get("location") or {}).get("name", ""),
                j.get("absolute_url"), "", [], j.get("updated_at", "")))
    return jobs


def fetch_lever(cfg, queries):
    """Official public Lever postings API — configure company slugs in
    config.json 'lever_boards'."""
    jobs = []
    for board in cfg.get("lever_boards", [])[:12]:
        try:
            data = _get_json(
                f"https://api.lever.co/v0/postings/{board}?mode=json",
                retries=0)
        except Exception:
            continue
        for j in data if isinstance(data, list) else []:
            if not _RELEVANT_TITLE.search(j.get("text") or ""):
                continue
            cats = j.get("categories") or {}
            jobs.append(_job(
                "lever", j.get("text"), board.title(),
                cats.get("location", ""), j.get("hostedUrl"),
                j.get("descriptionPlain", "")[:1500],
                [cats.get("team"), cats.get("commitment")],
                str(j.get("createdAt", ""))))
    return jobs


# ------------------------------------------------- best-effort scraped feeds

def fetch_linkedin(cfg, queries):
    """LinkedIn public guest job feed (no login). Can rate-limit or change
    markup at any time — treat as best-effort. Keep polling gentle."""
    location = cfg.get("location", "India")
    jobs = []
    for q in queries[:3]:
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/"
               f"search?keywords={urllib.parse.quote(q)}"
               f"&location={urllib.parse.quote(location)}&start=0")
        raw = _get(url, retries=1)
        for card in re.split(r"<li[\s>]", raw)[1:]:
            link = re.search(r'href="(https://[^"]*linkedin\.com/jobs/view/[^"]+)"', card)
            title = re.search(r'base-search-card__title[^>]*>\s*(.*?)\s*</h3>', card, re.S)
            company = re.search(r'<a[^>]*hidden-nested-link[^>]*>\s*(.*?)\s*</a>', card, re.S)
            loc = re.search(r'job-search-card__location[^>]*>\s*(.*?)\s*</span>', card, re.S)
            when = re.search(r'datetime="([^"]+)"', card)
            if link and title:
                jobs.append(_job(
                    "linkedin", _strip_html(title.group(1)),
                    _strip_html(company.group(1)) if company else "",
                    _strip_html(loc.group(1)) if loc else location,
                    link.group(1).split("?")[0],
                    "", [], when.group(1) if when else ""))
    return jobs


def fetch_naukri(cfg, queries):
    """Naukri unofficial search API. Naukri now requires a recaptcha token
    for anonymous calls, so this only works with a browser cookie: open
    naukri.com logged in, copy the Cookie header from any jobapi request in
    DevTools > Network, and paste it into config.json as
    {"naukri": {"cookie": "..."}} (or the NAUKRI_COOKIE env var)."""
    cookie = _cfg_key(cfg, "naukri", "cookie", "NAUKRI_COOKIE")
    jobs = []
    for q in queries[:2]:
        url = ("https://www.naukri.com/jobapi/v3/search?noOfResults=20"
               "&urlType=search_by_keyword&searchType=adv"
               f"&keyword={urllib.parse.quote(q)}&pageNo=1"
               "&src=jobsearchDesk")
        headers = {
            "appid": "109", "systemid": "Naukri", "clientid": "d3skt0p",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": ("https://www.naukri.com/"
                        + urllib.parse.quote(q.replace(" ", "-")) + "-jobs"),
        }
        if cookie:
            headers["Cookie"] = cookie
        try:
            data = _get_json(url, headers=headers, retries=0)
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 406):
                raise RuntimeError(
                    "Naukri blocks anonymous API calls (recaptcha). Paste a "
                    "browser Cookie into config.json naukri.cookie — or get "
                    "Naukri listings via jsearch (free RapidAPI key).")
            raise
        if data.get("message") == "recaptcha required":
            raise RuntimeError(
                "Naukri cookie expired — refresh naukri.cookie in config.json")
        for j in data.get("jobDetails", []):
            placeholders = {p.get("type"): p.get("label")
                            for p in j.get("placeholders", [])}
            jdurl = j.get("jdURL", "")
            if jdurl and not jdurl.startswith("http"):
                jdurl = "https://www.naukri.com" + jdurl
            jobs.append(_job(
                "naukri", j.get("title"), j.get("companyName"),
                placeholders.get("location", ""), jdurl,
                j.get("jobDescription"),
                [s for s in (j.get("tagsAndSkills") or "").split(",") if s],
                j.get("footerPlaceholderLabel", "")))
    return jobs


# ------------------------------------------------------- optional key-based

def fetch_adzuna(cfg, queries):
    app_id = _cfg_key(cfg, "adzuna", "app_id", "ADZUNA_APP_ID")
    app_key = _cfg_key(cfg, "adzuna", "app_key", "ADZUNA_APP_KEY")
    if not app_id or not app_key:
        return []
    country = (cfg.get("adzuna") or {}).get("country", "in")
    jobs = []
    for q in queries[:3]:
        url = (f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
               f"?app_id={app_id}&app_key={app_key}"
               f"&what={urllib.parse.quote(q)}&results_per_page=50")
        for j in _get_json(url).get("results", []):
            jobs.append(_job(
                "adzuna", j.get("title"),
                (j.get("company") or {}).get("display_name"),
                (j.get("location") or {}).get("display_name", ""),
                j.get("redirect_url"), j.get("description"), [],
                j.get("created", "")))
    return jobs


def fetch_jsearch(cfg, queries):
    key = _cfg_key(cfg, "jsearch", "rapidapi_key", "JSEARCH_RAPIDAPI_KEY")
    if not key:
        return []
    jobs = []
    for q in queries[:2]:
        query = f"{q} in {cfg.get('location', 'India')}"
        url = ("https://jsearch.p.rapidapi.com/search"
               f"?query={urllib.parse.quote(query)}&num_pages=1&date_posted=week")
        data = _get_json(url, headers={
            "X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
        for j in data.get("data", []):
            city = j.get("job_city") or ""
            country = j.get("job_country") or ""
            jobs.append(_job(
                "jsearch", j.get("job_title"), j.get("employer_name"),
                ", ".join(x for x in (city, country) if x),
                j.get("job_apply_link"), j.get("job_description"),
                (j.get("job_required_skills") or []),
                j.get("job_posted_at_datetime_utc") or ""))
    return jobs


def fetch_findwork(cfg, queries):
    key = _cfg_key(cfg, "findwork", "api_key", "FINDWORK_API_KEY")
    if not key:
        return []
    jobs = []
    for q in queries[:2]:
        data = _get_json(
            f"https://findwork.dev/api/jobs/?search={urllib.parse.quote(q)}",
            headers={"Authorization": f"Token {key}"})
        for j in data.get("results", []):
            jobs.append(_job(
                "findwork", j.get("role"), j.get("company_name"),
                j.get("location") or ("Remote" if j.get("remote") else ""),
                j.get("url"), j.get("text"), j.get("keywords"),
                j.get("date_posted", "")))
    return jobs


def fetch_jooble(cfg, queries):
    key = _cfg_key(cfg, "jooble", "api_key", "JOOBLE_API_KEY")
    if not key:
        return []
    jobs = []
    for q in queries[:2]:
        body = json.dumps({"keywords": q,
                           "location": cfg.get("location", "")}).encode()
        data = _get_json(f"https://jooble.org/api/{key}", method="POST",
                         data=body, headers={"Content-Type": "application/json"})
        for j in data.get("jobs", []):
            jobs.append(_job(
                "jooble", j.get("title"), j.get("company"),
                j.get("location", ""), j.get("link"), j.get("snippet"),
                [j.get("type")], j.get("updated", "")))
    return jobs


def fetch_usajobs(cfg, queries):
    key = _cfg_key(cfg, "usajobs", "api_key", "USAJOBS_API_KEY")
    email = _cfg_key(cfg, "usajobs", "email", "USAJOBS_EMAIL")
    if not key or not email:
        return []
    jobs = []
    for q in queries[:2]:
        data = _get_json(
            "https://data.usajobs.gov/api/search?Keyword="
            + urllib.parse.quote(q) + "&ResultsPerPage=25",
            headers={"Host": "data.usajobs.gov", "User-Agent": email,
                     "Authorization-Key": key})
        for item in (data.get("SearchResult") or {}).get("SearchResultItems", []):
            d = item.get("MatchedObjectDescriptor", {})
            jobs.append(_job(
                "usajobs", d.get("PositionTitle"),
                d.get("OrganizationName"),
                ", ".join(l.get("LocationName", "")
                          for l in (d.get("PositionLocation") or [])[:2]),
                d.get("PositionURI"),
                (d.get("UserArea") or {}).get("Details", {}).get("JobSummary", ""),
                [], d.get("PublicationStartDate", "")))
    return jobs


FETCHERS = {
    "remotive": fetch_remotive,
    "remoteok": fetch_remoteok,
    "arbeitnow": fetch_arbeitnow,
    "weworkremotely": fetch_weworkremotely,
    "jobicy": fetch_jobicy,
    "himalayas": fetch_himalayas,
    "workingnomads": fetch_workingnomads,
    "themuse": fetch_themuse,
    "hnhiring": fetch_hnhiring,
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "linkedin": fetch_linkedin,
    "naukri": fetch_naukri,
    "adzuna": fetch_adzuna,
    "jsearch": fetch_jsearch,
    "findwork": fetch_findwork,
    "jooble": fetch_jooble,
    "usajobs": fetch_usajobs,
}


def run_fetchers(fetchers, cfg, queries, log, label=""):
    """Run a dict of fetchers concurrently; a failing source never kills
    the poll. Returns (jobs, errors)."""
    all_jobs, errors = [], {}
    with ThreadPoolExecutor(max_workers=min(10, max(1, len(fetchers)))) as ex:
        futures = {ex.submit(fn, cfg, queries): name
                   for name, fn in fetchers.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                jobs = [j for j in fut.result(timeout=50)
                        if j["url"] and j["title"]]
                all_jobs.extend(jobs)
                log(f"  {label}{name}: {len(jobs)} results")
            except Exception as e:
                errors[name] = f"{type(e).__name__}: {e}"
                log(f"  {label}{name}: FAILED ({errors[name]})")
    return all_jobs, errors


def fetch_all(cfg, queries, log):
    enabled = cfg.get("sources", list(FETCHERS))
    fetchers = {n: FETCHERS[n] for n in enabled if n in FETCHERS}
    return run_fetchers(fetchers, cfg, queries, log)
