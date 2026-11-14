---
type: Test
affected:
  - Show ads
date: 2026-11-14
fault: adManualGc
kind: flag
name: 2026-11-14 flag:adManualGc
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
  - 0.7
  - 0.3
  - 1.0
  - 0.1
  - 0.0
  - 0.5
window_s: 76
EXERCISED:
  - "[[Service/ad]]"
---
