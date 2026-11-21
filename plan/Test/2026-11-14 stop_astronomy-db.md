---
type: Test
affected:
  - Add to cart
  - Place an order
  - Show recommendations
  - View a product
date: 2026-11-14
fault: astronomy-db
kind: stop
name: 2026-11-14 stop_astronomy-db
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
  - 2.3
  - 2.3
  - 2.3
  - 0.0
  - 2.3
  - 0.8
  - 0.2
window_s: 60
EXERCISED:
  - "[[Datastore/astronomy-db]]"
---
