---
name: sync-simple-docs
description: Sync the simple docs in docs/site/ (the GitHub Pages site) with the detailed docs and the code. Use when a design doc, an ADR, the coverage table, the CLI or the setup files change, when CI says "run the sync-simple-docs skill", or to write or update a page of the site.
---

# Sync the simple docs

`docs/site/` is the GitHub Pages site: the **landing page** of the product. Its readers are OpsFleet reviewers (first), engineers who want a quick look (second) and Executives (third). The tone is "look what we built": features and what the reader gets, not a report on the assignment. The detailed docs stay on github.com and are the source of truth (P24 in `docs/design-principles.md`).

There are two kinds of page:

- A **derived** page is rewritten from the detailed docs in plain words. It owns no numbers, values or rules.
- A **source** page owns its facts: commands, steps and scenarios. The detailed docs link to it.

[PAGES.md](PAGES.md) has the spec of each page: its file, kind, reader, sources and outline.

## Steps

1. **Select the pages.** If the user names pages, use them. If the user names changed files, or a branch, find each page whose sources include a changed file (the source map in PAGES.md). Otherwise, select all pages. Done when you have a list of page files.
2. **Read the sources.** For each selected page, read its spec in PAGES.md and every source that the spec lists, in full. For a source page, also run the commands that it documents, or read the code that makes them (`--help` output, `pyproject.toml`, `.env.example`, `scripts/`). Done when you can name the source of each statement that you will write.
3. **Write each page.** Follow its outline in PAGES.md and the rules below. Keep the file name and the heading anchors of a page that exists, because people share its URLs. Done when each outline item is on the page.
4. **Check each page** against every rule below, one rule at a time. Done when each rule passes on each page.
5. **Build** with `NO_MKDOCS_2_WARNING=1 uv run --locked --only-group docs mkdocs build --strict`. The build also checks the anchors of links between site pages. Done when it passes with no warning.
6. **Report** to the user: the pages that changed, and each **disagreement** that you found between the detailed docs, the code and the site. Write a disagreement as: what each source says, with its file and line. Fix only the site. The detailed docs and the code stay as they are. Done when each changed page and each disagreement is in the report.

## Rules

### Text

- Write in ASD-STE100 Simplified Technical English and in English (`AGENTS.md`). A sentence has 25 words or fewer. A bold item label, a heading and a table cell do not count as a sentence. Write customer text again in STE; do not quote it.
- Use the words of the reader, not of the code. Product, service and file names are permitted (BigQuery, Cloud Run, Gemini, SQLite, `executives.json`). Internal names are not: ports, classes, modules, functions and the names of HLD building blocks (write "Input check" or "a check before the language model", not "Input guard"). General words such as "the agent" and "the sales warehouse" are permitted.
- When the text of a page uses a glossary term (`CONTEXT.md`), such as Executive, Brand scope, Saved Report or Trio, explain it in plain words at its first use in the text of that page. Diagram labels and examples do not count as a first use. Do not link to `CONTEXT.md`.
- Put the most useful information first: each page and each section starts with what the reader needs most.
- Write about the product and what the reader gets. No site page names a requirement ID (R1–R8, AC-…, EX.…) or an acceptance criterion. Present each feature as what the reader gets, not as an answer to the assignment. A feature headline starts with the name of the feature that a reader knows, then a short benefit: "Tracing and metrics: see every step".

### Facts

- A derived page has no numbers, values or rules that a detailed doc owns: no thresholds, limits, budgets, retry counts, model IDs, time windows or brand names. Say what happens. The one exception is "$0" for the cost of the prototype on Home.
- Keep links few. Home has no links to the detailed docs, except one footer line. On How it works and Key decisions, each `##` or `###` section has one link at most. PAGES.md says where the links go. A link to a detailed doc is a full github.com URL on `main`, for example `[HLD §10](https://github.com/modvala/data-chat-assistant/blob/main/docs/design/hld.md#10-destructive-operations)`.
  A GitHub anchor is the heading in lower case, with spaces changed to `-` and other punctuation removed: `### 8.1 Layers` → `#81-layers`. A punctuation mark between two spaces (`Safety & PII`) gives `--` on GitHub but `-` on the site.
- Links between pages in `docs/site/` are relative (`how-it-works.md`).
- In a heading of a site page, write `and`, not `&`, and put no other punctuation mark between two spaces. Then the anchor is the same on the site and on github.com.
- Each statement agrees with its source. When two sources do not agree, write what the HLD and the ADRs say, and report the disagreement (step 6).
- On a source page, the code wins over `cli.md`, because the page owns the commands. Values that the CLI prints, or that a command needs, are permitted on a source page.
- Describe a part that the design shows but that has no code on `main` as a future feature (see Badges).

### Badges

A feature has one of two badges:

| Badge | When |
| --- | --- |
| **Available now** | The feature has code on `main`: the Code column of `docs/requirements-coverage.md` has a link for it, or the code exists (for example Docker). |
| **Coming next** | The feature is designed, but it has no code on `main`. |

Check the code, not the Mark column: a Bonus item with code is **Available now**. Write the badge as a bold line under the heading: `**Available now**` or `**Coming next**`. The production setup on Google Cloud has its own section and no badge.

### Examples

- An example input is one shell command, one question or one CLI command in its own `bash` or `text` code block. Material adds a copy button to each block.
- An example output is in a `text` block. It shows the **shape** of the Answer, with no figures from the data. The data is synthetic and it changes (P19). The exceptions are the Home hero and the example session of the CLI design block on Home (see PAGES.md). They use invented figures, and a line says so.
- Number the inputs of one Demo tour scenario (1, 2, 3), and use the same numbers in "What you see". A key press, such as `Ctrl+C`, or another reply to the same prompt can be in the text.
- Each example must run on the CLI on `main`. An input counts as tested when it ran on the CLI, or when it is the same input as a tested Demo tour scenario. If you cannot run it, say so on the status line and in the report.

### Layout

Each page must read correctly on the site and on github.com (P24). So use only these constructs:

- Markdown headings, lists, tables, links and `text`, `bash` and `mermaid` code blocks.
- In a numbered list, indent a code block with 4 spaces.
- A note: a Markdown blockquote (`>`).
- Two variants, such as the prototype and production: two headed sections, one after the other.


### Diagrams

- Use Mermaid. A diagram has 10 nodes or fewer, and plain labels. When the source has more parts, group them, or name the other parts in the text.
- Use `flowchart TB` when a chain has more than 5 nodes. An `LR` chain that long is too small to read on the site.
- Put one sentence before each diagram that says what to look at.

### Page frame

- The page starts with a `#` heading. Home has no status line: its badges show the status. Each other page has a status line after the heading. On How it works and Key decisions, it says what is available now and what is coming next. On a source page, it says if the commands are tested on `main`.
- The "Last updated" date comes from the git plugin. Do not write a date.
