#!/usr/bin/env python3
"""List the N newest articles from a fotospor.com.tr category page as JSON."""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 15
BASE = "https://www.fotospor.com.tr"


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def main():
    p = argparse.ArgumentParser(
        description="List newest fotospor.com.tr articles in a category."
    )
    p.add_argument(
        "--category",
        required=True,
        help="Category slug, e.g. besiktas, fenerbahce, galatasaray, futbol, basketbol",
    )
    p.add_argument(
        "--count", type=int, default=5, help="Number of articles to return (default 5)"
    )
    args = p.parse_args()

    url = f"{BASE}/{args.category}/"
    try:
        status, page = fetch(url)
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"http {e.code} for {url}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"fetch error: {type(e).__name__}: {e}\n")
        return 1

    if status != 200:
        sys.stderr.write(f"http {status} for {url}\n")
        return 1

    pat = re.compile(
        r'href="(/' + re.escape(args.category) + r'/([a-z0-9-]+)-(\d+))"'
    )
    seen = {}
    for m in pat.finditer(page):
        path, slug, aid = m.group(1), m.group(2), m.group(3)
        seen[aid] = {"id": aid, "slug": slug, "url": BASE + path}

    items = sorted(seen.values(), key=lambda x: int(x["id"]), reverse=True)[
        : args.count
    ]

    if not items:
        sys.stderr.write(
            f"warning: no articles found for category '{args.category}' "
            f"(check spelling — try 'besiktas', 'fenerbahce', 'galatasaray', "
            f"'futbol', 'basketbol')\n"
        )

    sys.stdout.write(json.dumps(items, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
