---
type: Function
critical: true
description: A visitor opens the cart.
journeys:
  - user_view_cart
name: View cart
promise_min: 60
ENTERS:
  - "[[Service/frontend-proxy]]"
USES:
  - "[[Service/cart]]"
  - "[[Service/frontend]]"
  - "[[Service/frontend-proxy]]"
---
