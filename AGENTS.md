# Notes for coding agents

Slowest Link checks each recovery promise in a continuity plan against what the function really depends on. The plan
is a Relate graph stored as Markdown notes in `plan/`.

- Agent skill: [`.claude/skills/slowest-link/SKILL.md`](.claude/skills/slowest-link/SKILL.md). It covers the graph,
  the tools and the rules. Read it before answering a question about promises, outages or restore order.
- MCP server: `python -m slowest_link mcp` (stdio), declared for Claude Code in [`.mcp.json`](.mcp.json).
- Before adding a network call from one service to another, run
  `python -m slowest_link guard --call "<source>-><target>" --for "<function>"`. Exit code 1 means a promise breaks.
- Every number in an answer comes from a tool or command output.
- Never write to `plan/` through Cypher. People edit its notes, and the trace import writes the evidence.
- Tests: `python -m pytest`. Lint and types: `ruff check .`, `ruff format --check .`, `mypy`.
