#!/usr/bin/env python3
"""
Analyze scheduler job errors from the SwissUnihockeyStats admin API.

Usage:
    python scripts/analyze_scheduler_errors.py [--host HOST] [--port PORT] [--pin PIN]

Example:
    python scripts/analyze_scheduler_errors.py --pin 1717
"""

import argparse
import http.cookiejar
import json
import sys
import tempfile
import urllib.request
import urllib.parse
from collections import Counter


def login(opener: urllib.request.OpenerDirector, base_url: str, pin: str) -> None:
    data = urllib.parse.urlencode({"pin": pin}).encode()
    req = urllib.request.Request(f"{base_url}/admin/login", data=data, method="POST")
    try:
        opener.open(req)
    except urllib.error.HTTPError as e:
        if e.code not in (302, 303):
            raise


def fetch_scheduler(opener: urllib.request.OpenerDirector, base_url: str) -> dict:
    resp = opener.open(f"{base_url}/admin/api/scheduler")
    return json.loads(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze scheduler job errors")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--pin", default="", help="Admin PIN (prompts if omitted)")
    parser.add_argument("--full", action="store_true", help="Show full tracebacks")
    args = parser.parse_args()

    pin = args.pin or input("Admin PIN: ")
    base_url = f"http://{args.host}:{args.port}"

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    print(f"Logging in to {base_url} ...")
    login(opener, base_url, pin)

    print("Fetching scheduler history ...\n")
    data = fetch_scheduler(opener, base_url)

    hist = data.get("history", [])
    errors = [h for h in hist if h["status"] == "error"]
    done = [h for h in hist if h["status"] == "done"]
    running = [h for h in hist if h["status"] in ("running", "pending")]

    print(f"History total : {len(hist)}")
    print(f"  done        : {len(done)}")
    print(f"  errors      : {len(errors)}")
    print(f"  running/pend: {len(running)}")

    if not errors:
        print("\nNo errors in history.")
        sample = hist[:5]
        if sample:
            print("\nSample jobs:")
            for h in sample:
                print(f"  {h['policy']} S{h['season']}  status={h['status']}  stats={h.get('stats')}")
        return

    # Group by first error line
    groups: Counter = Counter()
    for e in errors:
        err = e.get("error") or ""
        first = err.split("\n")[0][:120]
        groups[first] += 1

    print(f"\n{'='*60}")
    print(f"Error summary ({len(errors)} total)")
    print(f"{'='*60}")
    for msg, count in groups.most_common():
        print(f"  x{count:>3}  {msg}")

    print(f"\n{'='*60}")
    print("Details (up to 10 errors)")
    print(f"{'='*60}")
    for e in errors[:10]:
        print(f"\n--- {e['policy']} S{e['season']} [{e['job_id']}] ---")
        err = (e.get("error") or "no error text")
        lines = err.split("\n")
        limit = len(lines) if args.full else 10
        for line in lines[:limit]:
            print(f"  {line}")
        if not args.full and len(lines) > 10:
            print(f"  ... ({len(lines) - 10} more lines, use --full to expand)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except urllib.error.URLError as e:
        print(f"Connection error: {e.reason}", file=sys.stderr)
        sys.exit(1)
