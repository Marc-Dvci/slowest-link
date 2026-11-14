---
type: Function
critical: false
description: The shop suggests related products.
journeys:
  - user_get_recommendations
name: Show recommendations
promise_min: 480
ENTERS:
  - "[[Service/frontend-proxy]]"
USES:
  - "[[Service/frontend]]"
  - "[[Service/frontend-proxy]]"
  - "[[Service/recommendation]]"
---
