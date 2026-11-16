"""Texts that our code makes: refusals (cli.md C11) and notices.

A refusal never says which rule or which word caused it (HLD 8.9).
"""

from dca.core.answer import Notice, Refusal, RefusalReason

_REFUSALS: dict[str, tuple[str, str, str]] = {
    "pii": (
        "I can't show personal data",
        "Customer names, email addresses and addresses are protected.",
        "I can show Customers by ID, or give totals for a group.",
    ),
    "scope": (
        "This is outside your brands",
        "You can analyze only the brands in your Brand scope.",
        "I can show the same analysis for your brands. Type /scope to see them.",
    ),
    "not_analysis": (
        "I can only help with sales analysis",
        "Ask a question about the sales data.",
        'For example: "What was the revenue last month?" or "Who are the top 10 Customers by total spend?"',
    ),
    "threshold": (
        "This group is too small to show",
        "Groups with fewer than 5 Customers are hidden.",
        "Use a wider group, for example a state in place of a city.",
    ),
    "budget": (
        "This question needs too much data",
        "The question needs more work than one question can use.",
        "Use a shorter period, fewer columns or a smaller group.",
    ),
}


def refusal(reason: RefusalReason, body: str | None = None) -> Refusal:
    title, default_body, suggestion = _REFUSALS[reason]
    return Refusal(reason=reason, title=title, body=body or default_body, suggestion=suggestion)


def error_notice(trace_id: str) -> Notice:
    return Notice(
        level="error",
        title="The data service did not answer",
        body="Please try again in a minute. Your session continues.",
        trace_id=trace_id,
    )
