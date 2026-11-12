# AGENTS.md

## Project conventions

- **Language**: everything in this repository is written in English: code, comments, docs, commit messages, issues, PRs and project board items.
- **Explanations**: write all text that explains something in ASD-STE100 Simplified Technical English. This applies to docs, code comments, commit messages, issues, PRs, project board items and chat replies to the user. Write chat replies in English, also when the user writes in a different language. Keep customer text in `docs/requirements/` as the customer wrote it.
- **Diagrams**: when you explain a flow, a sequence, a structure or a relation, make a Mermaid diagram in a `mermaid` code block. Use the diagram in place of the text. Add only the text that the diagram cannot show. This applies to docs, issues, PRs and chat replies to the user.

## Coding guidelines

These rules come from the [Karpathy guidelines](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/.cursor/rules/karpathy-guidelines.mdc). They put caution before speed. For a very small task, use your judgment.

1. **Think before you code.** Before you change code, write your assumptions. If a request has more than one meaning, show the meanings and ask which one is correct. If a simpler method is possible, tell the user. If a part is not clear, stop and ask about that part.
2. **Keep it simple.** Write the minimum code that solves the problem. Add only the features, abstractions, configuration and error handling that the task needs now. If shorter code can do the same work, use the shorter code.
3. **Make surgical changes.** Change only the lines that the request needs: each changed line must connect to the request. Use the style of the code that is there. Remove the imports, variables and functions that your change made unused. If you find other unused code or other problems, tell the user and keep that code as it is.
4. **Work to a goal that you can check.** Change each task into a goal with a check. For example, "fix the bug" becomes "write a test that shows the bug, then make the test pass". For a task with many steps, write a short plan with a check for each step. Continue until all checks pass.
- **Customer requirements** live in `docs/requirements/`. Treat them as the source of truth for what the customer asked for.

## Agent skills

### Issue tracker

Issues live in GitHub Issues of `modvala/data-chat-assistant` and are tracked on the "Data Chat Assistant" GitHub Project board. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
