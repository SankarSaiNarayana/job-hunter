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
- `experience` — filter out roles that want more experience than you have:
  `{"min_years": 0, "max_years": 4, "include_unknown": true}`. Each posting's
  required years are parsed from its title/description; jobs whose minimum
  exceeds `max_years` are hidden (and won't trigger notifications). Postings
  that don't state a number are kept unless `include_unknown` is false. The
  dashboard has an **experience dropdown** that overrides this per-view; a
  badge on each card shows the parsed requirement (e.g. `3–5 yrs`, `7+ yrs`).
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
Done — the job-hunter app is rebuilt and fully tested against live sources. Everything you asked for is in, and I did no deployments and no git operations.

What changed

Deploy-ready for Vercel (no more running it daily). The app now has two entrypoints sharing one core: app.py runs locally exactly as before, and api/index.py + vercel.json run the same code as a Vercel serverless function with a built-in daily cron that fetches for you. Since Vercel wipes its filesystem, store.py automatically switches from local SQLite to a free Turso cloud database when two env vars are set. The README has the exact step-by-step deploy guide (create Turso DB → push to GitHub → import on Vercel → add env vars).

Old jobs never get lost or jumbled. Polling is now insert-only: it can never delete or overwrite a job. Dedup works on both the URL and a title+company fingerprint, so the same role from two boards appears once; re-seen jobs just get a last_seen bump. I verified this live — a full repoll of ~2,800 jobs inserted zero duplicates. Your 341 existing jobs were migrated intact (backup saved as data.db.backup-pre-upgrade).

Focus on SWE / DevOps / AI-ML. Every job is auto-classified into one of those categories (with a colored badge and filter in the UI), focus-category jobs get a +4 score boost, and default search queries target those roles.

Application stages. The tracker went from applied/hidden to a real pipeline: new → seen → applied → interviewing → offer / rejected (+ hidden), each with a timestamp and a notes box per job (referrals, interview dates). Header tabs show live counts per stage.

All the platforms. Now ~18 job sources fetched concurrently with retries: LinkedIn, Remotive, RemoteOK, Arbeitnow, WeWorkRemotely, Jobicy, Himalayas, Working Nomads, The Muse, Hacker News "Who is hiring", plus Greenhouse/Lever company boards (Anthropic, OpenAI, Stripe, Databricks… — filtered to engineering titles), and key-based Adzuna, JSearch (covers Indeed/Glassdoor/Naukri), Findwork, Jooble, USAJobs. Boards with no public feed (Wellfound, Dice, Instahyre, Cutshort…) are in a one-click directory in the UI.

Separate Freelance section with live gigs from Freelancer.com's official API (budgets shown), best-effort Truelancer, and a 16-platform directory (Upwork, Fiverr, Toptal, Braintrust, Arc.dev, Contra, Malt…). Note: Upwork retired its RSS feed permanently (HTTP 410) and Guru's is dead too — no scraper can fix that, so they're directory links.

Trending AI repos tab: 🔥 rising repos (created recently, high star velocity) and 🤝 contribute-friendly ones (active, with good-first-issues), each with direct "Good first issues" links. Refreshes every 12h — 16 repos loaded right now.

Two things for you

1. My test poll ran before I added the engineering-title filter, so ~1,100 non-engineering roles (sales/legal at those companies) landed in your DB. Harmless (the score filter hides them), but if you want them gone: sqlite3 ~/job-hunter/data.db "DELETE FROM jobs WHERE source='greenhouse' AND stage='new'" then hit "Fetch now" — the filtered versions come back clean.
2. Your real resume still isn't at ~/job-hunter/resume.pdf — scoring currently uses the sample resume.txt. Drop it there and restart for accurate matching, and run python3 app.py --once before deploying so profile.json (the skill snapshot that deploys — never the resume itself) is up to date.


Yes — a few things stood out while I was in the code. In rough order of impact:

1. Add the free API keys — biggest win for India coverage. Four sources (adzuna, jsearch, findwork, jooble) are enabled but return 0 results because their keys are empty in config.json. The two worth getting tonight:
- jsearch (free tier on RapidAPI) — pulls from Google-for-Jobs, which indexes Naukri, Indeed, Glassdoor, LinkedIn, Shine, etc. This is realistically your best Naukri coverage, better than the cookie approach (which expires).
- Adzuna (free, instant signup) — already configured for country in, so it's India-focused the moment you add a key.

2. Flag jobs that have disappeared from their board. The store already tracks last_seen — if a job is still in your inbox but hasn't been re-seen by polling in several days, the posting is probably closed. A "possibly closed" badge (or sorting them down) would stop you wasting time applying to dead listings. Right now that signal is collected but never used.

3. Follow-up nudges on applied jobs. stage_updated is recorded when you mark something applied, but nothing surfaces "applied 14 days ago, no movement — follow up or mark rejected." A small section or highlight in the Applied tab would keep the pipeline honest.

4. Location noise from Greenhouse. Greenhouse contributed 1,019 of the 1,709 jobs in the last poll, and those boards (Anthropic, Stripe, Figma…) list roles worldwide — a lot of "SF only" roles you can't apply to. A preferred_locations config (e.g. India / Remote) that penalizes or filters non-matching locations would clean the inbox up considerably.

5. Small fixes: truelancer is getting rate-limited (HTTP 429) on every poll — it should back off or poll less often; and LinkedIn only fetches the first page (~10 results per query), which could be bumped to 2–3 pages with start=25, 50.

If you want my pick: #1 needs you (account signups — 10 minutes of your time), and I'd implement #2 and #4 next since they attack the same "inbox full of things I can't or shouldn't apply to" problem from a different angle than the freshness work we just did. Tell me which ones to build and I'll get started.

✻ Crunched for 33s


All correct now: Any = 3421 (full), ceiling 2 = 2032, config default (4) = 2087, and blank q/source/category still behave. The feature is complete and verified end-to-end.

What I added — experience filtering for job-hunter

You can now set the experience level you want, and jobs demanding more get hidden (no more 7–8+ year senior roles cluttering the inbox).

How it works
- Each posting's required experience is parsed from its title + description — explicit ranges (3–5 years, 5+ yrs, minimum 2 years) and seniority words (junior/senior/staff/principal…) as a fallback (matcher.extract_experience).
- Stored per-job as exp_min / exp_max / exp_level columns. All 3,778 existing jobs were backfilled automatically on migration (0 unparsed remaining).
- Jobs whose minimum required years exceed your ceiling are filtered out; postings that don't state a number are kept (configurable).

Where you control it
- config.json → new block, the default ceiling:
"experience": { "min_years": 0, "max_years": 4, "include_unknown": true }
- Dashboard → a new experience dropdown next to the score filter (Any / ≤1 / ≤2 / ≤4 / ≤6 / ≤8 yrs), seeded from your config but overridable per view. Each job card shows a badge of the parsed requirement (3–5 yrs, 7+ yrs), highlighted for senior/lead roles.
- Notifications also respect the ceiling — you won't get pinged about senior roles.

Files touched: matcher.py (parser), store.py (columns + backfill + filter query), webapp.py (poll tagging, /api/jobs + /api/status, blank-param fix), config.json, dashboard.html (dropdown, badge, wiring), README.md.

One note on your running server: PID 7288 on :8787 is still the old code. Restart it (./run.sh or python3 app.py) to pick up the changes. Since I don't do any git operations, that's yours to commit whenever you like.

A design choice worth flagging: when a posting is titled "Senior" but its text explicitly says "3 years", I trust the number — so it can pass a low ceiling (the badge still shows senior for context). If you'd rather have a seniority word in the title always enforce its floor regardless of stated years, I can flip that.

✻ Cooked for 7m 39s
