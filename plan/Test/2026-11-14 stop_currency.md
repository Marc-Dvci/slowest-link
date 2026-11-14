---
type: Test
affected:
  - Place an order
date: 2026-11-14
fault: currency
kind: stop
name: 2026-11-14 stop:currency
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
  - 0.9
  - 0.8
  - 1.7
  - 0.8
  - 0.5
  - 0.8
  - 0.8
window_s: 60
EXERCISED:
  - "[[Service/currency]]"
---
