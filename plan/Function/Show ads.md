---
type: Function
critical: false
description: The shop shows contextual ads.
journeys:
  - user_get_ads
name: Show ads
promise_min: 1440
ENTERS:
  - "[[Service/frontend-proxy]]"
USES:
  - "[[Service/ad]]"
  - "[[Service/frontend]]"
  - "[[Service/frontend-proxy]]"
---
