# Page specs

The spec of each page of `docs/site/`. The nav in `mkdocs.yml` has the same order.

| Nav group | Page | File | Kind |
| --- | --- | --- | --- |
| — | Home | `index.md` | derived |
| Try it | Demo tour | `demo-tour.md` | source |
| Try it | Get started | `get-started.md` | source |
| Use it | Executive guide | `guide.md` | source |
| Under the hood | How it works | `how-it-works.md` | derived |
| Under the hood | Key decisions | `decisions.md` | derived |

## Source map

Use this map in step 1 to find the pages that a changed file affects.

| Changed file | Pages |
| --- | --- |
| `docs/design/hld.md` | Home, How it works, Key decisions |
| `docs/adr/*` | Key decisions |
| `docs/requirements-coverage.md` | Home, Demo tour |
| `docs/requirements/*` | Home |
| `docs/design/cli.md` | Home, Executive guide |
| `docs/tech-stack.md` | How it works |
| `pyproject.toml`, `.env.example`, `scripts/*`, `executives.json` | Get started, Executive guide |
| `src/dca/cli/*` | Executive guide, Demo tour, Get started |
| `src/dca/setup_bq.py`, `compose.yaml`, `docker/*`, `config/defaults.toml`, `tests/test_live.py` | Get started |
| `src/dca/core/messages.py`, `src/dca/app/turn_api.py` | Executive guide, Demo tour |
| Any other file in `src/` | Home (the badges) |
| `docs/site/demo-tour.md` | Home (the demo links) |

## Home (`index.md`)

**Reader:** all three readers. Page type: a product landing page. **Sources:** `docs/requirements/2026-11-12-client-technical-assignment.md` (the 8 topics to cover), `docs/design/hld.md` §23 and §26 (designed extensions), `docs/requirements-coverage.md` (badges), `docs/design/hld.md` (§1, §4.1, §8, §10, §12–§18), `docs/design/cli.md` (Answer model, Accessibility), `docs/site/demo-tour.md` (scenario anchors), the code on `main`.

**Out:** requirement IDs, labels of the assignment, setup steps, and links to the detailed docs except the footer.

Outline:

1. **Hero:** one to three sentences on what the product is and for whom. Then one example question in a `text` block, and a full example Answer in a second `text` block, in the layout that the CLI really draws (`src/dca/cli/render.py`; where it differs from `cli.md`, the code wins): a title, a KPI row, two or three findings, Action items with an owner and a metric to watch, and the provenance line. The figures and the brand names are invented but realistic, so that the Answer looks real. Use "last quarter" and "Q2", not a year or a date. Put one line under it: "An example with invented figures."
2. **At a glance:** one table with one row for each of the 8 topics of the assignment, the core chat and the terminal chat (CLI), in the order of the feature sections. Columns: "Feature" (its known name, such as "Tracing and metrics" or "Golden Bucket"), "How it works" (one short line on the solution, for example "OpenTelemetry trace for each question, `/trace` and a metrics command"), and the badge. No requirement IDs.
3. **Feature sections**, in this order. Each section has a short positive headline, a badge (see Badges), two or three sentences (what you get, then one sentence on how the technical solution does it), a small Mermaid diagram only when it says more than the text, and at most one link: "See it in the demo", to the Demo tour scenario that shows the feature best. A setup feature, such as Docker, links to its section of Get started in place of a scenario.

   | Headline | Covers | What to show |
   | --- | --- | --- |
   | Chat with your sales data: ask in plain words | Core chat | Text-to-SQL at run time, follow-up questions, reports with Action items, `/save` |
   | Safety and PII masking: your data stays safe | Safety and PII | Brand scope in two layers, SQL check, small groups hidden, output check, red-team tests |
   | Delete confirmation: nothing is deleted without your yes | Destructive operations | Preview, exact reply, Undo, audit log |
   | Resilience: it does not break | Resilience | Self-correction, "Did you mean…", retries, backup model, budgets, `Ctrl+C`, chaos mode |
   | Tracing and metrics: see every step | Observability | Provenance line, `/sql`, OpenTelemetry trace for each question, `/trace`, the metrics command |
   | The terminal chat (CLI): made for daily use | Extra | What you see: session header, status line, Answer panel, provenance line. The main commands in one short list, with a link to the Executive guide. Plain, ASCII and no-color modes for screen readers |
   | Runs on any machine | Extra | uv, Docker, $0 cost |
   | Executive profile: learns how you like your Answers | Learning loop | Learned format, depth and length, `/profile`, your edit wins |
   | Golden Bucket: learns from your analysts | Hybrid intelligence | A golden dataset of approved expert analyses (question, SQL, report), retrieval of similar ones, the analyst review loop |
   | Persona: the CEO sets the tone | Persona | Edit form, versions, preview and rollback, safety layer locked |
   | Evaluation: checked before release | Quality | Eval set with reference SQL in CI, LLM judge, side-by-side UX test |
   | Ready for Google Cloud (after the System design and CLI design blocks) | Production design | Cloud Run, IAP, Firestore, Sensitive Data Protection and Model Armor in one diagram; no badge |

   A "Coming next" section says what the feature will do, in two or three sentences.
4. **System design:** a block after "Evaluation" and before "Ready for Google Cloud". One architecture diagram with 10 nodes or fewer (from HLD §4.1: the Executive, the CLI, the checks before and after the language model, the agent, the language model as not trusted, the sales warehouse, the stores). Then the main design ideas, one line each, from `docs/design-principles.md`: the language model is not trusted; safety is in the code and in the data, not in the prompt (P8); the language model never sees raw personal data (P9); the language model only plans a delete, and the code does it (P11); ports and adapters, so the same core runs in the prototype and on Google Cloud (P6); configuration, not code (P17). No principle IDs on the page.
5. **CLI design:** a block after "System design". From `docs/design/cli.md` and the code: the parts of the screen (session header, prompt, status line, Answer panel, provenance line) in one example session in a `text` block; the symbols and what each one means (for example ✓ ⊘ ⚠ ▲ ▼ ◆); the color roles in one sentence; the Answer components (KPI row, table, Action items, notice, confirmation panel, trace view); accessibility (each status has a word and a symbol, not only a color; plain, ASCII and no-color modes). Where `cli.md` and the code differ, the code wins. The feature section "The terminal chat (CLI)" stays short and links to this block, not to the guide; the full command list stays in the Executive guide.
6. **Also designed:** one short list of the other designed features with no code, one line each. Take them from the HLD (§12.4 Metric catalog, §23 extension points, §26) and the coverage extras: for example the Metric catalog, the result cache, the circuit breaker, Saved Reports by email, a web chat on the same API, and the review console for analysts.
7. **Try it:** relative links to the Demo tour and Get started, and to the Executive guide.
8. **Footer:** one line, "For engineers: the full design is on GitHub", with one link to the repository.

## How it works (`how-it-works.md`)

**Reader:** reviewers and engineers. **Sources:** `docs/design/hld.md` §4.1, §6.1, §8.1, §18, §19; `docs/tech-stack.md`. Page type: an architecture doc.

**Out:** ports, code layers, the SQL rules, the Turn API, the progress events and all values (limits, budgets, model IDs).

Outline: four diagrams. Each one has a section with a sentence before the diagram, two to four sentences after it, and one link to its HLD section.

1. **Context:** the Executive, the CLI, the agent, the language model, the sales warehouse and the stores. Show which parts the Executive talks to and which parts hold data.
2. **Building blocks:** two headed sections, "In the prototype" (HLD §19) and "In production on Google Cloud" (HLD §18). One diagram each. Name the main services in production and the local files in the prototype, in groups. Give each part that has no code on `main` the badge Coming next.
3. **One Turn:** about 6 steps from the question to the Answer (HLD §6.1, main path), in plain words: check the message, find similar past analyses, write SQL, check and limit the SQL, run it, check the Answer. Give a step that has no code on `main` the badge Coming next.
4. **Safety layers:** input check → SQL check → Brand scope → output check (HLD §8.1). Say that each layer works alone, so one failure does not leak data.

## Key decisions (`decisions.md`)

**Reader:** reviewers and engineers. **Sources:** `docs/design/hld.md` §24, `docs/adr/*`.

**Out:** the full trade-off text and the consequences of the ADRs. Link to them.

Outline: a short intro, then all decisions of HLD §24 in four groups. Each decision is in exactly one group:

- **Safety and access:** who sees which data, PII, deletes and the guards.
- **Platform:** the framework, compute, state, channel, transport and cloud.
- **AI and knowledge:** the models, retrieval, metrics, evaluation and learning.
- **Operations:** observability and changes that people make at run time, such as the Persona.

The page intro has one link to HLD §24, and a short "Words on this page" list that explains the glossary terms of the page. Each decision is one list item with two sentences: `**<Decision>:** We chose X, not Y. <Z>.` Take X from the Choice column, Y from Alternatives and Z (the reason, in plain words) from Trade-off. A decision with an ADR names it in plain text at the end, for example `(ADR 0001)`, with no link. Each group that names an ADR ends with one link to the ADR folder on github.com. Each item agrees with HLD §24 and with its ADR. When they do not agree, write what the ADR says and report it.

## Get started (`get-started.md`)

**Reader:** a reviewer or an engineer who runs the prototype. An Executive does not install anything. **Sources:** `pyproject.toml`, `.env.example`, `scripts/setup-gcp.sh`, `src/dca/setup_bq.py`, `compose.yaml`, `docker/*`, `config/defaults.toml`, `tests/test_live.py`, the `--help` output of the commands. Page type: a quick start.

**Out:** the design, and the reasons for the tools. Link to How it works and Key decisions.

Outline, in this order: prerequisites; install with `uv sync` (uv is the only dependency manager, P19); configure `.env`; the GCP setup script and ADC impersonation of `dca-agent`; `uv run setup-bq`; the first chat; run with Docker, as a second way; the offline and `live` tests and the metrics command; configuration reference; a troubleshooting table with the usual errors.

- Each step has one line that says **why** it is necessary.
- Each command is in its own `bash` block.

## Demo tour (`demo-tour.md`)

**Reader:** reviewers. **Sources:** the Must ACs of `docs/requirements-coverage.md`, the CLI, `src/dca/core/messages.py`, `src/dca/app/turn_api.py`.

**Out:** the setup steps (link to Get started) and the design of each feature (link to Home).

- One scenario for each Must AC, with the headings `## D<n>. <name>`, with no AC ID. Keep the headings, because the coverage table and Home link to their anchors.
- Each scenario has: the AC in plain words, the inputs (one input in each code block, numbered), and "What you see" with the same numbers.
- A scenario for a Bonus AC is added only when its code exists.
- Each scenario can run after the scenarios before it. When a scenario needs the state of an earlier one, such as the Saved Reports of D5, say so at its start.

## Executive guide (`guide.md`)

**Reader:** Executives. **Sources:** `docs/design/cli.md`, the `/help` output (`src/dca/cli/render.py`), `src/dca/core/messages.py` (refusal and notice texts), `src/dca/app/turn_api.py`, `executives.json`.

**Out:** the setup steps, the design and the internal names of the CLI components (C1–C17).

Sections, each with short examples that you can copy:

1. Start a session (prototype: `uv run chat --executive <id>`; production: sign-in through IAP).
2. Ask a question: suggested topics from the assignment, and follow-up questions.
3. Read an Answer: KPI rows, tables, charts, Action items, the provenance line, and why the figures come from queries and not from the LLM text.
4. When the agent says no: the refusal reasons in plain words, and what to do.
5. Reports: save, list, delete with a confirmation, and undo.
6. Your profile: only when `/profile` exists in `/help`.
7. When something fails: notices, `Ctrl+C`, and the trace ID with `/trace`.
8. Command and option reference, the same as `/help`.

Then a "For the CEO" section on how the CEO changes the Persona, with the badge **Coming next**.
