# CLAUDE.md

@AGENTS.md

## Orchestration rules (main session only)

- You are the orchestrator. You plan, delegate to subagents, verify, and merge. You do not write feature code yourself.
- Work one phase at a time from `docs/task-breakdown.md`. Never start a phase before the previous phase's gate is verified.
- Delegate each ticket to the subagent that owns its lane:
  - BE-core -> `backend-core`
  - BE-brief -> `backend-brief`
  - FE -> `frontend`
  - DATA -> `data`
- Run tickets in parallel only when their dependencies are merged AND their "Key files" do not overlap.
- After each ticket, delegate to `verifier` before marking it done. Update the Status column in `docs/task-breakdown.md`.
- At each phase gate: stop, summarise what was built, show test output, and wait for my approval before the next phase.
- LLM providers are switchable via `.env` (`openai`, `groq`, `anthropic`), separately for the app and for Hindsight. Never change the selected provider or model yourself; if a provider's rate limit or model capability blocks a ticket (for example, Hindsight's reflect needs tool calling), stop and report it to me with the evidence.
