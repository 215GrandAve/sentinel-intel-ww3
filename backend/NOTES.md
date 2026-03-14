# Backend notes

This backend keeps the semi-automated workflow intact:

1. `update.py` drafts `data/proposed.json`
2. human review happens outside the public site
3. `publish.py` archives the last known good snapshot and promotes the proposal to `latest.json`

## Optional live LLM generation

`update.py` can run in three modes:

- `--provider none` → uses the review packet as-is
- `--provider anthropic` → sends the prompt to Anthropic and expects JSON back
- `--provider openai` → sends the prompt to OpenAI and expects JSON back

Environment variables:

- `SENTINEL_LLM_PROVIDER=none|anthropic|openai`
- `ANTHROPIC_API_KEY=...`
- `ANTHROPIC_MODEL=claude-sonnet-4-5` (optional)
- `OPENAI_API_KEY=...`
- `OPENAI_MODEL=gpt-5.4` (optional)

The frontend never touches these keys. Public visitors only load the published JSON snapshots.
