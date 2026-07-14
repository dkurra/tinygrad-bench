# Chat logs (AI-use declaration)

This project was built end-to-end with Claude Code (Claude Fable 5), as declared in
REPORT.md. Contents:

- `transcript.md` — human-readable transcript of the full session.
- `claude_code_session.jsonl` — the same 714 messages in structured form.

All user and assistant text is preserved verbatim and unabridged. Only bulky tool
*outputs* (file dumps, test logs) are truncated with explicit `[N chars elided]`
markers, and the log necessarily ends just before the final packaging messages.
