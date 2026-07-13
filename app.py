"""Job Hunter — local entrypoint.

Run:  python3 app.py            (or ./run.sh)   → dashboard + background poller
      python3 app.py --once     one poll cycle, then exit (for external cron)

The same code deploys to Vercel via api/index.py + vercel.json — see README.
"""
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import webapp

poll_now = threading.Event()


def notify_mac(title, message):
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}" sound name "Glass"'],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass


def poller_loop():
    while True:
        try:
            webapp.poll()
        except Exception as e:
            webapp.log(f"Poll error: {type(e).__name__}: {e}")
        cfg = webapp.load_config()
        interval = max(2, int(cfg.get("poll_minutes", 15))) * 60
        poll_now.wait(timeout=interval)
        poll_now.clear()


class Handler(webapp.HttpMixin, BaseHTTPRequestHandler):
    pass


def main():
    cfg = webapp.load_config()
    profile = webapp.load_profile(cfg)
    webapp.log(f"Resume parsed: {len(profile['skills'])} skills, "
               f"roles={profile['roles'][:5]}")
    webapp.log(f"Search queries: {webapp.get_queries(cfg, profile)}")

    webapp.notify_hook = notify_mac

    if "--once" in sys.argv:
        summary = webapp.poll()
        webapp.log(f"Done: {summary}")
        return

    webapp.refresh_hook = poll_now.set
    threading.Thread(target=poller_loop, daemon=True).start()

    port = cfg.get("port", 8787)
    webapp.log(f"Dashboard: http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
