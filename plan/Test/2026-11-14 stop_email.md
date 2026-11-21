---
type: Test
affected: []
date: 2026-11-14
fault: email
kind: stop
name: 2026-11-14 stop_email
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
  - 0.8
  - 0.7
  - 0.2
  - 0.7
  - 0.7
  - 0.7
  - 0.8
window_s: 60
EXERCISED:
  - "[[Service/email]]"
---
