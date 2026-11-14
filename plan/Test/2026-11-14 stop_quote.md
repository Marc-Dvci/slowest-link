---
type: Test
affected:
  - Place an order
date: 2026-11-14
fault: quote
kind: stop
name: 2026-11-14 stop:quote
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
  - 0.2
  - 0.2
  - 3.4
  - 0.5
  - 0.2
  - 0.4
  - 0.5
window_s: 60
EXERCISED:
  - "[[Service/quote]]"
---
