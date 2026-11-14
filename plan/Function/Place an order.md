---
type: Function
critical: true
description: A customer pays and the order is placed.
journeys:
  - user_checkout_single
  - user_checkout_multi
name: Place an order
promise_min: 60
ENTERS:
  - "[[Service/frontend-proxy]]"
USES:
  - "[[Service/cart]]"
  - "[[Service/checkout]]"
  - "[[Service/currency]]"
  - "[[Service/email]]"
  - "[[Service/frontend]]"
  - "[[Service/frontend-proxy]]"
  - "[[Service/payment]]"
  - "[[Service/shipping]]"
---
