# The LLM has no delete tool, and code catches the confirmation

Scope: both

The LLM can only call `plan_delete`. This tool finds the Saved Reports that match the request, but it changes nothing. Our code shows the preview and a short confirmation code. The code is bound to the Executive, the session and a hash of the exact set of report IDs. Our code reads the next message of the Executive *before* the LLM sees it. Only an exact match of the code starts the soft delete and the audit log entry. Thus no prompt injection can make the LLM delete reports.

```mermaid
sequenceDiagram
    participant E as Executive
    participant C as Code
    participant L as LLM
    participant S as Report store
    E->>L: Delete all reports mentioning Customer 123
    L->>C: plan_delete(customer_ids=[123])
    C->>S: Find own reports that mention 123
    C->>E: Preview and confirmation code
    E->>C: Confirmation code
    C->>C: Check the Executive, session and ID-set hash
    C->>S: Soft delete and audit log entry
    C->>E: Result and undo option
```

## Considered options

- **ADK `require_confirmation` on a delete tool**: less code, but the framework then makes a safety decision, and the LLM still holds a delete tool. This conflicts with P6 and P11.
