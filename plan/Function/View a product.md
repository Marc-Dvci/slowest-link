---
type: Function
critical: true
description: A visitor opens a product page.
journeys:
  - user_browse_product
name: View a product
promise_min: 60
ENTERS:
  - "[[Service/frontend-proxy]]"
USES:
  - "[[Service/frontend]]"
  - "[[Service/frontend-proxy]]"
  - "[[Service/product-catalog]]"
---
