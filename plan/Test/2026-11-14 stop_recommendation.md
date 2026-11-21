---
type: Test
affected:
  - Show recommendations
date: 2026-11-14
fault: recommendation
kind: stop
name: 2026-11-14 stop_recommendation
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
  - 0.3
  - 0.3
  - 1.5
  - 0.6
  - 5.8
  - 0.5
  - 0.6
window_s: 60
EXERCISED:
  - "[[Service/recommendation]]"
---
