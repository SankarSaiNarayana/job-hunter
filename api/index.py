"""Vercel serverless entrypoint. vercel.json rewrites every path here, and
the daily cron hits /api/cron. All state lives in Turso (see store.py), so
nothing is lost between invocations."""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import webapp  # noqa: E402


class handler(webapp.HttpMixin, BaseHTTPRequestHandler):
    pass
