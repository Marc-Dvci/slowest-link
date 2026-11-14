# Examples

Outputs of the command line on the committed plan, each with the command that produced it.

| Example | Command | Output |
|---|---|---|
| Every check, every view | `python -m slowest_link check --as-of 2026-11-14` | [`check-2026-11-14.txt`](check-2026-11-14.txt) |
| One function in each view | `python -m slowest_link explain "View cart"` | [`explain-view-cart.txt`](explain-view-cart.txt) |
| The database is down for 3 hours | `python -m slowest_link whatif "Our managed PostgreSQL database is down. Estimated restore: 3 hours."` | [`whatif-database-3h.txt`](whatif-database-3h.txt) |
| Kafka is down for 3 hours | `python -m slowest_link whatif "Kafka brokers unavailable, recovery expected in 3 hours."` | [`whatif-kafka-3h.txt`](whatif-kafka-3h.txt) |
| The home page starts calling the catalogue | `python -m slowest_link guard --call "frontend->product-catalog" --for "Browse the shop"` | [`guard-home-page-catalogue.txt`](guard-home-page-catalogue.txt) |
| A coding agent records the change in the plan, and the hook answers | Claude Code, headless, in a clone of the repository | [`agent-session.md`](agent-session.md) |
