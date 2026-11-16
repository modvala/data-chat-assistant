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

**Reader:** all three readers. Page type: a product landing page. **Sources:** `docs/requirements/2026-11-12-client-technical-assignment.md` (the 8 topics to cover), `docs/requirements-coverage.md` (badges), `docs/design/hld.md` (§1, §4.1, §8, §10, §12–§18), `docs/design/cli.md` (Answer model, Accessibility), `docs/site/demo-tour.md` (scenario anchors), the code on `main`.

**Out:** requirement IDs, labels of the assignment, setup steps, and links to the detailed docs except the footer.

Outline:

1. **Hero:** one to three sentences on what the product is and for whom. Then an example question in a `text` block, and the shape of its Answer in a second `text` block, in the CLI layout of `cli.md`: a KPI row, Action items and the provenance line. Use placeholders such as `▲ n%` and `<brands>`, not data.
2. **Feature sections**, in this order. Each section has a short positive headline, a badge (see Badges), two or three sentences (what you get, then one sentence on how the technical solution does it), a small Mermaid diagram only when it says more than the text, and at most one link: "See it in the demo", to the Demo tour scenario that shows the feature best. A setup feature, such as Docker, links to its section of Get started in place of a scenario.

   | Headline | Covers | What to show |
   | --- | --- | --- |
   | Ask in plain words | Core chat | Reports with Action items, follow-up questions, `/save` |
   | Your data stays safe | Safety and PII | Brand scope in two layers, small groups hidden, red-team tests |
   | Nothing is deleted without your yes | Destructive operations | Preview, exact reply, Undo, audit log |
   | It does not break | Resilience | Self-correction, "Did you mean…", backup model, budgets, `Ctrl+C`, chaos mode |
   | See every step | Observability | Provenance line, `/sql`, `/trace`, the metrics tool |
   | A CLI that is good to use | Extra | Progress states; plain, ASCII and no-color modes for screen readers |
   | Runs on any machine | Extra | uv, Docker, $0 cost |
   | Learns how you like your Answers | Learning loop | Executive profile and `/profile` |
   | Learns from your analysts | Hybrid intelligence | Golden Bucket of expert examples and the review loop |
   | The CEO sets the tone | Persona | Edit form, versions, preview and rollback |
   | Checked before release | Quality | Eval set in CI, LLM judge, UX test |
   | Ready for Google Cloud | Production design | Cloud Run, IAP, Firestore, Sensitive Data Protection and Model Armor in one diagram; no badge |

   A "Coming next" section says what the feature will do, in two or three sentences.
3. **Also on the roadmap:** one short list for the Metric catalog, the result cache, the circuit breaker, Saved Reports by email and a web chat on the same API.
4. **Try it:** relative links to the Demo tour and Get started, and to the Executive guide.
5. **Footer:** one line, "For engineers: the full design is on GitHub", with one link to the repository.

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

- One scenario for each Must AC, with the headings `## D<n>. <name> (AC-<id>)`. Keep the headings, because the coverage table and Home link to their anchors.
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
