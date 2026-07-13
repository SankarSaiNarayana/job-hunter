# 🎯 Job Hunter

Give it your resume → it continuously pulls relevant **jobs** (focused on
Software Engineering / DevOps / AI-ML), **freelance gigs**, and **trending AI
repos worth contributing to** — scores everything against your actual skills,
and shows it all in one dashboard with a full application pipeline
(applied → interviewing → offer / rejected).

Runs two ways with the same code:

- **Local**: `./run.sh` → dashboard at http://localhost:8787, polls in the
  background, macOS notifications on high matches. Storage: SQLite (`data.db`).
- **Cloud (Vercel-style)**: deploy once, a daily cron fetches for you — no
  laptop needed. Storage: Turso (free tier), so **nothing is ever lost between
  fetches or deploys**.

## Quick start (local)

```bash
# 1. Drop your resume here (pdf, docx, txt, or md):
cp ~/Downloads/MyResume.pdf ~/job-hunter/resume.pdf

# 2. Run it:
cd ~/job-hunter && ./run.sh

# 3. Open the dashboard:
open http://localhost:8787
```

`python3 app.py --once` runs a single fetch cycle and exits (handy for cron).

## Your data is never lost

- Every poll is **insert-only**: new jobs are added, jobs seen again just get
  their `last_seen` timestamp bumped. Nothing is deleted or overwritten.
- Dedup is two-layer: by URL **and** by a normalized title+company
  fingerprint, so the same role arriving from two boards shows up once.
- Your pipeline stages and notes live on the job row and are never touched by
  polling.

## The three tabs

| Tab | What's in it |
|---|---|
| **Jobs** | Aggregated postings from ~18 sources, scored against your resume, classified SWE / DevOps / AI-ML |
| **Freelance** | Live gigs from Freelancer.com (+ best-effort Truelancer), plus a directory of 16 renowned platforms (Upwork, Fiverr, Toptal, Braintrust, Arc.dev, Contra…) |
| **AI Repos** | Trending GitHub AI repos: 🔥 *rising* (new, gaining stars fast) and 🤝 *contribute* (active, with good-first-issues) — refreshed every 12h |

## Application pipeline

Every job/gig moves through stages — use the dropdown or quick buttons on
each card, and attach notes (referrals, contacts, interview dates):

```
new → seen → applied → interviewing → offer
                     ↘ rejected            hidden (anytime)
```

The header tabs filter by stage and show live counts, so you always know
what's applied vs. pending.

## Where jobs come from

**No key needed (on by default):**

| Source | Coverage |
|---|---|
| `linkedin` | LinkedIn public guest feed — best-effort, may rate-limit |
| `remotive` `remoteok` `arbeitnow` `weworkremotely` `jobicy` `himalayas` `workingnomads` | Remote jobs worldwide |
| `themuse` | The Muse (Software Engineering / Data / IT categories) |
| `hnhiring` | Hacker News monthly "Who is hiring?" thread |
| `greenhouse` `lever` | Official public APIs of company boards you pick in `greenhouse_boards` / `lever_boards` (default: Anthropic, OpenAI, Databricks, Stripe, Figma, Cloudflare…) — filtered to engineering titles |
| `naukri` | Off by default — blocks with reCAPTCHA; its postings arrive via `jsearch` |

**Free API key unlocks more (add to `config.json` locally or env vars on Vercel):**

| Source | Get a key | Env var |
|---|---|---|
| `jsearch` | https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch — aggregates **Indeed / Glassdoor / LinkedIn / Naukri** via Google-for-Jobs | `JSEARCH_RAPIDAPI_KEY` |
| `adzuna` | https://developer.adzuna.com — India + 15 countries | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` |
| `findwork` | https://findwork.dev/developers/ | `FINDWORK_API_KEY` |
| `jooble` | https://jooble.org/api/about | `JOOBLE_API_KEY` |
| `usajobs` | https://developer.usajobs.gov (US federal) | `USAJOBS_API_KEY`, `USAJOBS_EMAIL` |

Boards with no public feed (Wellfound, Dice, Monster, ZipRecruiter, Instahyre,
Cutshort, Hirist, Internshala…) are one click away in the dashboard's
platform directory, and most of their postings arrive via `jsearch` anyway.

## Deploy to Vercel (fetches daily without your laptop)

The filesystem on serverless platforms is wiped between runs, so cloud mode
stores everything in [Turso](https://turso.tech) (free tier: 500 DBs, 9GB).

```bash
# 1. Create the database (once):
brew install tursodatabase/tap/turso
turso auth signup
turso db create job-hunter
turso db show job-hunter --url        # → TURSO_DATABASE_URL
turso db tokens create job-hunter    # → TURSO_AUTH_TOKEN

# 2. Make sure profile.json exists (created automatically when you run
#    locally with your resume in place) — it's what the cloud uses to score:
python3 app.py --once

# 3. Push this folder to a GitHub repo, then import it at vercel.com/new.

# 4. In Vercel → Project → Settings → Environment Variables, add:
#      TURSO_DATABASE_URL, TURSO_AUTH_TOKEN
#      CRON_SECRET (any random string — protects /api/cron)
#      plus any source keys (JSEARCH_RAPIDAPI_KEY, ADZUNA_APP_ID, ...)
```

That's it: `vercel.json` already routes the app and schedules a daily cron
(`30 3 * * *` UTC ≈ 9am IST) that hits `/api/cron` and fetches everything.
The "Fetch now" button also works in the deployed dashboard.

> Vercel Hobby allows daily crons; on Pro you can raise the frequency by
> editing the schedule in `vercel.json`. Local and cloud can share the same
> Turso DB — set the two env vars locally and your applied/interview stages
> stay in sync everywhere.

Notes: your resume and `data.db` are `.gitignore`d — only the skill profile
(`profile.json`) is deployed, never the resume itself.

## config.json

- `focus` — categories to boost: `swe`, `devops`, `aiml` (each adds +4 score).
- `search_queries` — what to search on query-based boards. Default targets
  SWE / DevOps / ML / AI engineer roles.
- `freelance_queries` — searches for the Freelance tab.
- `greenhouse_boards` / `lever_boards` — company career boards to watch
  (official public APIs — add any company that uses Greenhouse or Lever).
- `repos.topics` — GitHub topics for the AI Repos tab.
- `github_token` (or `GITHUB_TOKEN` env) — optional, raises GitHub rate limits.
- `location`, `poll_minutes`, `notify_min_score`, `extra_keywords` — as before.

## How scoring works

Your resume is scanned against a ~250-term skill/role vocabulary. Each job
gets points: your role in the title +6, a skill in the title +3, in tags +2,
in the description +1, and +4 if the job classifies into one of your focus
categories (SWE / DevOps / AI-ML). Matched keywords show as chips on each
card so you can see *why* it matched.

## Why it doesn't auto-apply

LinkedIn, Naukri and Upwork all prohibit automated applications and enforce
it with CAPTCHAs and account bans. This tool automates what's safe —
discovery, matching, dedup, tracking — so applying takes one click.

## Files

- `app.py` — local entrypoint (server + background poller)
- `api/index.py` + `vercel.json` — cloud entrypoint + daily cron
- `webapp.py` — shared routes/polling core used by both entrypoints
- `store.py` — storage: SQLite locally, Turso in the cloud; migrations included
- `sources.py` — job fetchers (concurrent, retrying, fail-independent)
- `freelance.py` — gig fetchers + platform directory
- `repos.py` — trending AI repos via GitHub search
- `matcher.py` — resume profile, scoring, SWE/DevOps/AI-ML classification
- `resume.py` — pdf/docx/txt resume loading
- `dashboard.html` — the UI
- `data.db` — your local job database (never deleted by the app)
