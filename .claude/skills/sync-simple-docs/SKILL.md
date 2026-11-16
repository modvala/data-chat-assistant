---
name: sync-simple-docs
description: Sync the simple docs in docs/site/ (the GitHub Pages site) with the detailed docs and the code. Use when a design doc, an ADR, the coverage table, the CLI or the setup files change, when CI says "run the sync-simple-docs skill", or to write or update a page of the site.
---

# Sync the simple docs

`docs/site/` is the GitHub Pages site. Its readers are OpsFleet reviewers (first), engineers who want a quick look (second) and Executives (third). The site is the first page that reviewers see, and a high-level demonstration of the product. The detailed docs stay on github.com and are the source of truth (P24 in `docs/design-principles.md`).

There are two kinds of page:

- A **derived** page is rewritten from the detailed docs in plain words. It owns no numbers, values or rules.
- A **source** page owns its facts: commands, steps and scenarios. The detailed docs link to it.

[PAGES.md](PAGES.md) has the spec of each page: its file, kind, reader, sources and outline.

## Steps

1. **Select the pages.** If the user names pages, use them. If the user names changed files, or a branch, find each page whose sources include a changed file (the source map in PAGES.md). Otherwise, select all pages. Done when you have a list of page files.
2. **Read the sources.** For each selected page, read its spec in PAGES.md and every source that the spec lists, in full. For a source page, also run the commands that it documents, or read the code that makes them (`--help` output, `pyproject.toml`, `.env.example`, `scripts/`). Done when you can name the source of each statement that you will write.
3. **Write each page.** Follow its outline in PAGES.md and the rules below. Keep the file name and the heading anchors of a page that exists, because people share its URLs. Done when each outline item is on the page.
4. **Check each page** against every rule below, one rule at a time. Done when each rule passes on each page.
5. **Build** with `NO_MKDOCS_2_WARNING=1 uv run --only-group docs mkdocs build --strict`. The build also checks the anchors of links between site pages. Done when it passes with no warning.
6. **Report** to the user: the pages that changed, and each **disagreement** that you found between the detailed docs, the code and the site. Write a disagreement as: what each source says, with its file and line. Fix only the site. The detailed docs and the code stay as they are. Done when each changed page and each disagreement is in the report.

## Rules

### Text

- Write in ASD-STE100 Simplified Technical English and in English (`AGENTS.md`). A sentence has 25 words or fewer. A bold item label, a heading and a table cell do not count as a sentence. Write customer text again in STE; do not quote it.
- Use the words of the reader, not of the code. Product, service and file names are permitted (BigQuery, Cloud Run, Gemini, SQLite, `executives.json`). Internal names are not: ports, classes, modules, functions and the names of HLD building blocks (write "Input check" or "a check before the language model", not "Input guard"). General words such as "the agent" and "the sales warehouse" are permitted.
- When the text of a page uses a glossary term (`CONTEXT.md`), such as Executive, Brand scope, Saved Report or Trio, explain it in plain words at its first use in the text of that page. Diagram labels and examples do not count as a first use. Do not link to `CONTEXT.md`.
- Put the most useful information first: each page and each section starts with what the reader needs most.

### Facts

- A derived page has no numbers, values or rules that a detailed doc owns: no thresholds, limits, budgets, retry counts, model IDs, time windows or brand names. Say what happens, and link to the detail. The one exception is a count that you compute from the rows of the coverage table, such as the status table on Home.
- Each `##` or `###` section of a derived page that summarizes a detailed doc ends with a **Details** line. When a section has subsections, only the subsections have one. The page intro and navigation sections, such as "Start here", have none, unless PAGES.md says otherwise. The Details line has one or more full github.com links to the source sections on `main`:
  `**Details:** [HLD §10 Destructive operations](https://github.com/modvala/data-chat-assistant/blob/main/docs/design/hld.md#10-destructive-operations)`
  A GitHub anchor is the heading in lower case, with spaces changed to `-` and other punctuation removed: `### 8.1 Layers` → `#81-layers`. A punctuation mark between two spaces (`Safety & PII`) gives `--` on GitHub but `-` on the site.
- Links between pages in `docs/site/` are relative (`how-it-works.md`). If the target page does not exist yet, link to its current source on github.com: `docs/demo.md` for the Demo tour, `README.md#setup` for Get started and `README.md#use` for the Executive guide.
- In a heading of a site page, write `and`, not `&`, and put no other punctuation mark between two spaces. Then the anchor is the same on the site and on github.com.
- Each statement agrees with its source. When two sources do not agree, write what the HLD and the ADRs say, and report the disagreement (step 6).
- When the design shows a part that has no code on `main`, give it the label of its AC from the coverage table, or **Production design** if it has no AC. When the part has more than one AC, use the label of the AC that is about the prototype (Must or Bonus). Do not describe it as a part of the prototype.

### Labels

Each acceptance criterion (AC) has one label. Take it from the "Mark" column of `docs/requirements-coverage.md`. Do not decide it.

| Mark | Label |
| --- | --- |
| Must | **Works in the prototype** |
| Bonus | **Planned extra** |
| Design, Design (optional) | **Production design** |

### Examples

- An example input is one shell command, one question or one CLI command in its own `bash` or `text` code block. Material adds a copy button to each block.
- An example output is in a `text` block. It shows the **shape** of the Answer, with no figures from the data. The data is synthetic and it changes (P19).
- Each example must run on the CLI on `main`. If you cannot run it, say so in the report.

### Layout

Each page must read correctly on the site and on github.com (P24). So use only these constructs:

- Markdown headings, lists, tables, links and `text`, `bash` and `mermaid` code blocks.
- Cards: an HTML block `<div class="grid cards" markdown>`, a blank line, a Markdown list, a blank line, `</div>`.
- A note: a Markdown blockquote (`>`).
- Two variants, such as the prototype and production: two headed sections, one after the other.


### Diagrams

- Use Mermaid. A diagram has 10 nodes or fewer, and plain labels. When the source has more parts, group them, or name the other parts in the text.
- Use `flowchart TB` when a chain has more than 5 nodes. An `LR` chain that long is too small to read on the site.
- Put one sentence before each diagram that says what to look at.

### Page frame

- The page starts with a `#` heading, then a status line. On a derived page, it says what the page shows: `**Status:** <what works in the prototype and what is only designed, from the coverage table>`. On a source page, it says if the commands are tested on `main`.
- The "Last updated" date comes from the git plugin. Do not write a date.
