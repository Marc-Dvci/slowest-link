---
type: Function
critical: true
description: A visitor adds a product to the cart.
journeys:
  - user_add_to_cart
name: Add to cart
promise_min: 60
ENTERS:
  - "[[Service/frontend-proxy]]"
USES:
  - "[[Service/cart]]"
  - "[[Service/frontend]]"
  - "[[Service/frontend-proxy]]"
  - "[[Service/product-catalog]]"
---
