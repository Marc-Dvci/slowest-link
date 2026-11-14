---
type: Function
critical: true
description: A visitor opens the shop's home page.
journeys:
  - user_index
  - user_session_start
name: Browse the shop
promise_min: 60
ENTERS:
  - "[[Service/frontend-proxy]]"
USES:
  - "[[Service/frontend]]"
  - "[[Service/frontend-proxy]]"
---
