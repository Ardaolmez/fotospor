---
name: fotospor-translate
description: Translate Turkish sports news from fotospor.com.tr to English. Use when the user pastes a https://www.fotospor.com.tr/ URL, asks to translate a fotospor article, or asks for the latest N articles from a fotospor category (besiktas, fenerbahce, galatasaray, trabzonspor, futbol, basketbol, etc.). Fetches each article, translates with strict adherence to the project glossary, auto-fixes any glossary mismatches before writing, and saves a Markdown file per article to ./output/.
---

# Fotospor translation workflow

The most important rule: **glossary terms must be translated exactly as the glossary says.** Term accuracy is the single most important quality bar. Re-read `.claude/skills/fotospor-translate/references/glossary.md` on every run — do not rely on memory of it from earlier conversations.

## When this skill applies

Trigger on any of:
- The user message contains a URL starting with `https://www.fotospor.com.tr/`.
- The user asks to translate a fotospor article (by URL or in the abstract).
- The user asks for the latest / newest / recent N articles from a fotospor category (`besiktas`, `fenerbahce`, `galatasaray`, `trabzonspor`, `futbol`, `basketbol`, `super-lig`, etc.).
- The user asks "what are the headlines on fotospor today" — treat as category mode, default to `futbol`, count 5.

## Inputs and modes

**URL mode** — input contains one or more `https://www.fotospor.com.tr/...` URLs. Translate every URL given.

**Category mode** — input names a category slug + a count. If the user said "latest" / "newest" / "recent" without a number, default to **5**. Common slugs: `besiktas`, `fenerbahce`, `galatasaray`, `trabzonspor`, `futbol`, `basketbol`. If you're unsure of the slug, run `list_category.py` once with your guess; if it returns `[]` and prints a warning, ask the user for the right slug.

If the input has both a URL and a category phrase, prefer URL mode.

## Step-by-step workflow

### 1. Resolve the article list

URL mode: collect every fotospor URL from the user's message into a list.

Category mode: run

```
python3 .claude/skills/fotospor-translate/scripts/list_category.py --category <slug> --count <N>
```

Parse the JSON array on stdout. If empty, stop and ask the user for a different slug.

### 2. Load the glossary

Read `.claude/skills/fotospor-translate/references/glossary.md`. The file is organised into multiple tables grouped by topic (Clubs, Officials, Football, Basketball, Volleyball, etc.). Parse **all** tables: scan every line, keep rows that start with `|`, skip header rows (where the first cell is `Turkish`) and separator rows (where cells are dashes). Each remaining data row has three pipe-separated cells: `Turkish`, `English`, `Notes`. Strip whitespace.

Identify which sport the article is about (use the URL category — `futbol`, `spor-toto-super-lig`, `besiktas`, `fenerbahce`, `galatasaray` etc. → football; `basketbol` → basketball; `voleybol` → volleyball) and prioritise that sport's section when a term has sport-specific entries (e.g. `smaç`, `defans`, `mola`, `blok`, `dripling`). For ambiguous terms, the cross-sport sections (Transfers, Match outcomes, Officials) always apply.

Hold this in memory for steps 4 and 5. Also re-read the **Translation rules** section at the top of the glossary file — those rules apply to every article.

### 3. Fetch each article

For each URL, run

```
python3 .claude/skills/fotospor-translate/scripts/fetch_article.py --url <URL>
```

Each line of stdout is one JSON record:

```
{ "url": ..., "id": "702669", "slug": "...", "category": "besiktas",
  "title": "...", "description": "...", "body_paragraphs": [...],
  "published": "...", "error"?: "..." }
```

If `error` is present, report that one URL to the user (`http_404`, `empty_extract`, etc.) and skip it — do not write a file for failed URLs.

### 4. Translate (you do this in-conversation)

For each successfully-fetched article, translate `title`, `description`, and every paragraph in `body_paragraphs`. Apply these rules in order:

1. **Glossary first.** Before producing any English sentence, scan the Turkish source for every Turkish term in the glossary (matching inflected forms — Turkish is agglutinative, so `sakatlık` covers `sakatlığı`, `sakatlandı`, `sakatlanan`; `transfer` covers `transferi`, `transferde`; `imza` covers `imzaladı`, `imzaya`). For each match, use the glossary's English term in your translation.
2. **Player names**: never translate. Verbatim with diacritics.
3. **Club names**: keep Turkish spelling with diacritics, even when the glossary lists them — the row exists to remind you not to anglicise.
4. **Scores, dates, numbers, ages, jersey numbers**: preserve verbatim. Don't re-format dates.
5. **Headlines**: translate for meaning, not word-for-word. Turkish sports headlines are rhetorical; render them as natural English you'd see in a sports section.
6. Body sentences: produce natural, journalistic English. Use the present perfect for recent events ("has signed", "has agreed") where the Turkish is `-DI`/perfective and the action is recent.

### 5. Glossary verification — auto-fix, don't just report

After the first-pass translation, do a verification sweep:

For each glossary row whose Turkish term appears in the source (matching inflected forms):
- Confirm the English term appears in the corresponding place in the translation.
- If it doesn't (you used a synonym, a paraphrase, or skipped it), **rewrite that paragraph of the translation to use the glossary term**. Don't stop at flagging the mismatch — fix it.
- If the glossary term is genuinely wrong for the context (e.g. `forma giydi` means "made appearances for", not literally "wore the jersey"), use the Notes column's guidance. If neither the English term nor the Notes fit, leave a single line in the Glossary check section explaining why and suggesting a glossary refinement.

After the auto-fix, do a second sweep to confirm. Only proceed to write when every glossary term that appeared in the source is rendered with its glossary English in the translation.

### 6. Write the output file

Ensure `./output/` exists (`mkdir -p output` via Bash if needed). Filename: `output/{id}-{slug}.md`. If the resulting filename exceeds 80 characters, truncate the slug portion (keep the leading `{id}-` intact). Use the **Output template** below verbatim.

### 7. Report in chat

Per article, print one line:

```
Wrote output/702669-besktasin-kalesinde-samba.md — "Beşiktaş'ın kalesinde samba: Gabriel Brazao" → "Samba in the Beşiktaş goal: Gabriel Brazao" (glossary: 7/7 consistent)
```

If any glossary mismatch could not be auto-fixed in step 5, list it on a sub-bullet with the suggested glossary refinement.

## Output template (one file per article)

```markdown
# {english_title}

> {english_description}

- **Source**: {url}
- **Article ID**: {id}
- **Category**: {category}
- **Published**: {published_iso_or_blank}
- **Translated**: {today_iso}

## Original (Turkish)

**{turkish_title}**

{turkish_description}

{turkish_body_paragraphs joined with one blank line between each}

## Translation (English)

**{english_title}**

{english_description}

{english_body_paragraphs joined with one blank line between each}

## Glossary check

- Glossary terms found in source: {n}
- Consistent in translation: {n_ok}
- Mismatches (after auto-fix): {n_mismatch}

If `n_mismatch == 0`: write the line `All glossary terms translated consistently.`

If `n_mismatch > 0`: include this table

| Turkish | Expected EN | Used in translation | Paragraph | Reason kept |
|---------|-------------|---------------------|-----------|-------------|
| ...     | ...         | ...                 | ...       | ...         |

(only include this table if you intentionally departed from the glossary; otherwise auto-fix.)
```

## Notes on robustness

- Don't translate the same article twice in one run — if the user lists a URL twice, dedupe by `id`.
- If `body_paragraphs` is empty but `title` is set, still write the file with just title + description; note `(body extraction failed — JSON-LD missing)` in the Glossary check section. This is signal that the page layout changed.
- If `published` is empty (not in JSON-LD), leave the field blank rather than guessing.
- Never invent missing details. If the source is short, the translation is short.

## Growing the glossary

When you encounter a Turkish sports term that's not in the glossary and matters for the article (a new player position, a tactic name, a competition), add a row to `references/glossary.md` and mention what you added in the chat summary. The user will review and refine.
