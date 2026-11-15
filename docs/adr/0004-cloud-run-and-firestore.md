# Production runs on Cloud Run with Firestore, not on Agent Platform Runtime

Scope: production

The turn service runs on Cloud Run and keeps all state in Firestore: sessions, pending confirmations, Saved Reports, the audit log and the Executive profiles. The confirmation flow and the audit log are core logic (P5), so we keep their state in our own store. The Executive profile must be structured and editable by the Executive, and Memory Bank keeps free-form memories. One store is also simpler to operate.

## Considered options

- **Gemini Enterprise Agent Platform Runtime with Sessions and Memory Bank** (formerly Vertex AI Agent Engine): less code and a native ADK deploy (`adk deploy agent_engine`), but more lock-in, unstructured memory, and pricing that we did not verify.
- **Cloud Run with Agent Platform Sessions for the conversation and Firestore for the rest**: two stores for one turn.
