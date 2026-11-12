# Client decisions (Slack, 2026-11-12)

> **Note:** This is a summary of the Slack answers. It is not the original customer text. Replace it with the original messages when they are available.

## Access (Harry)

- Access is by brand only.
- A manager owns one or more brands. The CEO sees all data.
- The manager-to-brand mapping can be a configuration file or an access table. We select which one.
- Customers, orders and metrics use only the purchases of brands in the manager's scope.

## PII (Harry)

- `user_id` or a stable pseudonym is permitted.
- Do not show names, email addresses, street addresses, postal codes or exact coordinates.
- Block row-by-row lists filtered by attributes such as age, or give an aggregate.

## Tools (Vlad)

- uv is preferred to pip.
