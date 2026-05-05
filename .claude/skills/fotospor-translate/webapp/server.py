#!/usr/bin/env python3
"""Local web app: paste a fotospor URL, get a side-by-side TR | EN translation.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...   # required for translation
    python3 .claude/skills/fotospor-translate/webapp/server.py
    # then open http://127.0.0.1:8000/

Stdlib only. Reuses scripts/fetch_article.py for HTTP/parsing and
references/glossary.md as the source of truth for terms. The glossary is sent
to Claude as a cached system prompt so repeated translations only pay the
glossary token cost once.
"""

import http.server
import json
import os
import socketserver
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from string import Template

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
SCRIPT_DIR = SKILL_DIR / "scripts"
GLOSSARY_PATH = SKILL_DIR / "references" / "glossary.md"

sys.path.insert(0, str(SCRIPT_DIR))
from fetch_article import fetch_one  # noqa: E402

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = os.environ.get("FOTOSPOR_MODEL", "claude-sonnet-4-6")
PORT = int(os.environ.get("FOTOSPOR_PORT", "8000"))


def load_glossary():
    return GLOSSARY_PATH.read_text(encoding="utf-8")


def build_system_blocks(glossary_text, category):
    instructions = (
        "You are a Turkish-to-English sports translator for fotospor.com.tr.\n\n"
        "RULES (apply on every translation):\n"
        "1. Apply the glossary below STRICTLY. Match inflected Turkish forms (the language is "
        "agglutinative — `sakatlık` may appear as `sakatlığı`, `sakatlandı`, etc.). After your "
        "first pass, do a self-check sweep: for every glossary Turkish term that appears in the "
        "source, confirm the glossary's English term is what you used. If not, rewrite that "
        "paragraph to use the glossary term. Don't just flag mismatches — fix them.\n"
        "2. Player names: verbatim with diacritics.\n"
        "3. Club names: keep Turkish spelling with diacritics (Beşiktaş, Fenerbahçe, VakıfBank).\n"
        "4. Scores, dates, numbers, ages: preserve verbatim.\n"
        "5. Headlines: render natural English, not word-for-word.\n"
        "6. Football articles use British football English: `manager` (not 'head coach'), `matchweek`, "
        "`fixture`, `boots`. Basketball and volleyball use `head coach`.\n"
        f"7. The article's URL category is `{category}`. Prioritise the matching sport section in "
        "the glossary when a term has sport-specific entries (e.g. `smaç`, `defans`, `mola`, "
        "`saha`, `blok`).\n\n"
        "OUTPUT: a single JSON object with exactly these keys:\n"
        '  {"title": "...", "description": "...", "body_paragraphs": ["...", "..."]}\n'
        "body_paragraphs must be 1:1 with the input paragraphs (same length, same order).\n"
        "No prose. No markdown fences. Just the JSON.\n\n"
        "=== GLOSSARY (source of truth) ===\n" + glossary_text
    )
    return [
        {
            "type": "text",
            "text": instructions,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def call_claude(article, glossary_text, api_key):
    paragraphs_in = article.get("body_paragraphs", []) or []
    user_msg = (
        "Translate this fotospor article. Return only the JSON object described in the system prompt.\n\n"
        f"TITLE_TR: {article.get('title','')}\n"
        f"DESCRIPTION_TR: {article.get('description','')}\n"
        "BODY_PARAGRAPHS_TR (one per line, prefixed with [index]):\n"
        + "\n".join(f"[{i}] {p}" for i, p in enumerate(paragraphs_in))
    )
    body = json.dumps(
        {
            "model": MODEL,
            "max_tokens": 8192,
            "system": build_system_blocks(glossary_text, article.get("category") or ""),
            "messages": [{"role": "user", "content": user_msg}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read().decode("utf-8"))
    text = resp["content"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    parsed = json.loads(text)
    usage = resp.get("usage", {}) or {}
    return parsed, usage


PAGE_TEMPLATE = Template(
    """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>fotospor TR → EN</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; margin: 0; background: #f6f6f6; color: #1a1a1a; }
  header { padding: 1.1rem 1.5rem; background: #0f1115; color: #fafafa; }
  header h1 { margin: 0; font-size: 1.05rem; font-weight: 600; }
  header p { margin: 0.2rem 0 0; font-size: 0.82rem; color: #9aa0aa; }
  .form-row { padding: 0.9rem 1.5rem; background: #fff; border-bottom: 1px solid #ececec; display: flex; gap: 0.6rem; }
  .form-row input[type=url] { flex: 1; padding: 0.55rem 0.7rem; font-size: 0.95rem; border: 1px solid #d0d0d0; border-radius: 4px; }
  .form-row button { padding: 0.55rem 1.1rem; background: #c20000; color: #fff; border: 0; border-radius: 4px; font-weight: 600; cursor: pointer; }
  .form-row button:disabled { background: #888; cursor: wait; }
  main { display: grid; grid-template-columns: 1fr 1fr; gap: 0.9rem; padding: 1.25rem; }
  .col { background: #fff; padding: 1.1rem 1.25rem; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); min-height: 220px; }
  .col h2 { margin: 0 0 0.4rem; font-size: 0.75rem; text-transform: uppercase; color: #888; letter-spacing: 0.06em; }
  .col h3 { margin: 0.3rem 0 0.5rem; font-size: 1.1rem; line-height: 1.3; }
  .col p { line-height: 1.55; margin: 0 0 0.7rem; }
  .col blockquote { border-left: 3px solid #c20000; margin: 0.4rem 0 0.9rem; padding: 0.2rem 0.7rem; color: #555; font-style: italic; }
  .meta { font-size: 0.78rem; color: #666; margin: 0.5rem 1.5rem 1rem; }
  .meta code { background: #eee; padding: 0.05rem 0.3rem; border-radius: 3px; font-size: 0.9em; }
  .error { padding: 0.9rem 1.5rem; background: #ffeded; color: #930000; border-bottom: 1px solid #fbcfcf; font-size: 0.9rem; white-space: pre-wrap; word-break: break-word; }
  .empty { color: #aaa; font-style: italic; }
  @media (max-width: 800px) { main { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>fotospor TR → EN</h1>
  <p>paste a fotospor.com.tr article URL · glossary applied automatically</p>
</header>
<form class="form-row" method="post" action="/translate" id="f">
  <input type="url" name="url" placeholder="https://www.fotospor.com.tr/..." required value="$URL" autofocus>
  <button type="submit" id="btn">Translate</button>
</form>
$ERROR
$META
<main>
  <section class="col">
    <h2>Türkçe</h2>
    $TR
  </section>
  <section class="col">
    <h2>English</h2>
    $EN
  </section>
</main>
<script>
document.getElementById('f').addEventListener('submit', () => {
  const b = document.getElementById('btn');
  b.textContent = 'Translating…';
  b.disabled = true;
});
</script>
</body>
</html>
"""
)


def html_escape(s):
    if s is None:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_section(title, description, paragraphs):
    if not title and not paragraphs and not description:
        return '<p class="empty">Paste a URL above and click Translate.</p>'
    parts = []
    if title:
        parts.append(f"<h3>{html_escape(title)}</h3>")
    if description:
        parts.append(f"<blockquote>{html_escape(description)}</blockquote>")
    for p in paragraphs:
        parts.append(f"<p>{html_escape(p)}</p>")
    return "\n".join(parts)


def render_page(url="", error=None, article=None, en=None, usage=None):
    error_html = (
        f'<div class="error">{html_escape(error)}</div>' if error else ""
    )
    meta_html = ""
    if article and not error:
        bits = []
        if article.get("category"):
            bits.append(f"category <code>{html_escape(article['category'])}</code>")
        if article.get("id"):
            bits.append(f"id <code>{html_escape(article['id'])}</code>")
        if article.get("published"):
            bits.append(f"published <code>{html_escape(article['published'])}</code>")
        if usage:
            bits.append(
                f"tokens in <code>{usage.get('input_tokens','?')}</code> "
                f"(cached <code>{usage.get('cache_read_input_tokens',0)}</code>) · "
                f"out <code>{usage.get('output_tokens','?')}</code>"
            )
        if bits:
            meta_html = f'<div class="meta">{" · ".join(bits)}</div>'
    tr_html = (
        render_section(
            article.get("title", ""),
            article.get("description", ""),
            article.get("body_paragraphs", []) or [],
        )
        if article
        else render_section("", "", [])
    )
    en_html = (
        render_section(
            en.get("title", ""),
            en.get("description", ""),
            en.get("body_paragraphs", []) or [],
        )
        if en
        else render_section("", "", [])
    )
    return PAGE_TEMPLATE.safe_substitute(
        URL=html_escape(url),
        ERROR=error_html,
        META=meta_html,
        TR=tr_html,
        EN=en_html,
    )


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, render_page())
        return self._send(404, render_page(error="Not found."))

    def do_POST(self):
        if self.path != "/translate":
            return self._send(404, render_page(error="Not found."))
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8")
        form = urllib.parse.parse_qs(raw)
        url = (form.get("url") or [""])[0].strip()
        if not url.startswith("https://www.fotospor.com.tr/"):
            return self._send(
                200,
                render_page(
                    url=url,
                    error="URL must start with https://www.fotospor.com.tr/",
                ),
            )
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return self._send(
                200,
                render_page(
                    url=url,
                    error=(
                        "ANTHROPIC_API_KEY is not set. Stop the server, run "
                        "`export ANTHROPIC_API_KEY=sk-ant-...`, then restart "
                        "with `python3 .claude/skills/fotospor-translate/webapp/server.py`."
                    ),
                ),
            )
        article = fetch_one(url)
        if article.get("error"):
            return self._send(
                200,
                render_page(
                    url=url,
                    error=f"Fetch failed: {article['error']}",
                    article=article,
                ),
            )
        try:
            glossary = load_glossary()
            en, usage = call_claude(article, glossary, api_key)
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8")
            except Exception:
                err_body = str(e)
            return self._send(
                200,
                render_page(
                    url=url,
                    error=f"Anthropic API error {e.code}: {err_body[:500]}",
                    article=article,
                ),
            )
        except json.JSONDecodeError as e:
            return self._send(
                200,
                render_page(
                    url=url,
                    error=f"Model returned non-JSON output ({e}). Try again.",
                    article=article,
                ),
            )
        except Exception as e:
            return self._send(
                200,
                render_page(
                    url=url,
                    error=f"Translation error: {type(e).__name__}: {e}",
                    article=article,
                ),
            )
        return self._send(
            200, render_page(url=url, article=article, en=en, usage=usage)
        )


def main():
    addr = ("127.0.0.1", PORT)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(addr, Handler) as srv:
        sys.stderr.write(
            f"fotospor-translate web app running at http://127.0.0.1:{PORT}/\n"
        )
        sys.stderr.write(
            f"  model: {MODEL}  glossary: {GLOSSARY_PATH}\n"
        )
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.stderr.write(
                "  warning: ANTHROPIC_API_KEY is not set. The form will render, but "
                "Translate will fail until you set it.\n"
            )
        sys.stderr.write("Press Ctrl+C to stop.\n")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            sys.stderr.write("\nshutting down\n")


if __name__ == "__main__":
    main()
