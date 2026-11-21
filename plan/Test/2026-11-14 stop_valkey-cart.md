---
type: Test
affected:
  - Add to cart
  - Place an order
  - View cart
date: 2026-11-14
fault: valkey-cart
kind: stop
name: 2026-11-14 stop_valkey-cart
not_recovered: []
recovery_journeys:
  - user_add_to_cart
  - user_browse_product
  - user_checkout_single
  - user_get_ads
  - user_get_recommendations
  - user_index
  - user_view_cart
recovery_s:
  - 1.0
  - 0.6
  - 1.3
  - 0.9
  - 0.0
  - 0.7
  - 1.2
window_s: 60
EXERCISED:
  - "[[Datastore/valkey-cart]]"
---
