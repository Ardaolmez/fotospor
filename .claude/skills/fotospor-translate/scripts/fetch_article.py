#!/usr/bin/env python3
"""Fetch a fotospor.com.tr article and emit JSON to stdout (one record per --url)."""

import argparse
import html
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

URL_RE = re.compile(r"/([^/]+)/([a-z0-9-]+)-(\d+)/?(?:\?.*)?$")


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


def parse_url(url):
    m = URL_RE.search(url)
    if not m:
        return None, None, None
    return m.group(1), m.group(2), m.group(3)


def clean_text(s):
    if not s:
        return ""
    s = re.sub(r"<script[^>]*>.*?</script>", " ", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def split_paragraphs(body_html):
    if not body_html:
        return []
    s = re.sub(r"<script[^>]*>.*?</script>", " ", body_html, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<iframe[^>]*>.*?</iframe>", " ", s, flags=re.DOTALL | re.IGNORECASE)
    parts = re.split(r"</p>|</div>", s, flags=re.IGNORECASE)
    out = []
    for part in parts:
        text = clean_text(part)
        if text and len(text) > 5:
            out.append(text)
    return out


def _loads_lenient(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r"[\x00-\x1f]+", " ", raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def extract_jsonld(page):
    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        page,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        data = _loads_lenient(m.group(1).strip())
        if data is None:
            continue
        candidates = []
        if isinstance(data, list):
            candidates.extend(data)
        elif isinstance(data, dict):
            if isinstance(data.get("@graph"), list):
                candidates.extend(data["@graph"])
            else:
                candidates.append(data)
        for c in candidates:
            if not isinstance(c, dict):
                continue
            t = c.get("@type")
            t_set = set(t) if isinstance(t, list) else {t}
            if t_set & {"NewsArticle", "Article", "ReportageNewsArticle"}:
                return c
    return None


def extract_title_h1(page):
    m = re.search(
        r'<h1[^>]*class="title[^"]*"[^>]*>(.*?)</h1>',
        page,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return clean_text(m.group(1)) if m else ""


def extract_meta_description(page):
    m = re.search(
        r'<meta\s+name="description"\s+content="(.*?)"',
        page,
        flags=re.IGNORECASE,
    )
    return clean_text(m.group(1)) if m else ""


def extract_body_html(page):
    """Slice the body container by counting <div> nesting depth from its open tag."""
    start = re.search(
        r'<div\s+class="content\s+font-size-18[^"]*"[^>]*>',
        page,
        flags=re.IGNORECASE,
    )
    if not start:
        return ""
    i = start.end()
    depth = 1
    open_re = re.compile(r"<div\b", re.IGNORECASE)
    close_re = re.compile(r"</div>", re.IGNORECASE)
    body_start = i
    while i < len(page):
        no = open_re.search(page, i)
        nc = close_re.search(page, i)
        if not nc:
            break
        if no and no.start() < nc.start():
            depth += 1
            i = no.end()
        else:
            depth -= 1
            if depth == 0:
                return page[body_start:nc.start()]
            i = nc.end()
    return page[body_start : body_start + 80000]


def to_record(url, page):
    category, slug, article_id = parse_url(url)
    title = ""
    description = ""
    body_paragraphs = []
    published = ""

    ld = extract_jsonld(page)
    if ld:
        description = clean_text(ld.get("description") or "")
        published = ld.get("datePublished") or ""

    title = extract_title_h1(page)
    if not title and ld:
        title = clean_text(ld.get("headline") or "")
        title = re.sub(r"\s*-\s*[^-]+\s+Haberleri\s*$", "", title)
    if not description:
        description = extract_meta_description(page)

    body_paragraphs = split_paragraphs(extract_body_html(page))

    if not body_paragraphs and ld:
        body = ld.get("articleBody") or ""
        if body:
            paras = [
                p.strip()
                for p in re.split(r"\n\s*\n+|\t+", body)
                if p.strip() and len(p.strip()) > 5
            ]
            body_paragraphs = paras if paras else [body.strip()]

    return {
        "url": url,
        "id": article_id or "",
        "slug": slug or "",
        "category": category or "",
        "title": title,
        "description": description,
        "body_paragraphs": body_paragraphs,
        "published": published,
    }


def fetch_one(url):
    try:
        status, page = fetch(url)
    except urllib.error.HTTPError as e:
        return {"url": url, "error": f"http_{e.code}"}
    except urllib.error.URLError as e:
        return {"url": url, "error": f"url_error:{e.reason}"}
    except Exception as e:
        return {"url": url, "error": f"exception:{type(e).__name__}:{e}"}

    if status != 200:
        return {"url": url, "error": f"http_{status}"}

    try:
        rec = to_record(url, page)
    except Exception as e:
        return {"url": url, "error": f"exception:{type(e).__name__}:{e}"}

    if not rec["title"] and not rec["body_paragraphs"]:
        rec["error"] = "empty_extract"
    return rec


def main():
    p = argparse.ArgumentParser(description="Fetch fotospor.com.tr article(s) and emit JSON.")
    p.add_argument("--url", action="append", required=True, help="Article URL (repeat for batch)")
    args = p.parse_args()
    for url in args.url:
        rec = fetch_one(url)
        sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
