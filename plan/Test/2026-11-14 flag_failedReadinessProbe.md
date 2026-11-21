---
type: Test
affected: []
date: 2026-11-14
fault: failedReadinessProbe
kind: flag
name: 2026-11-14 flag_failedReadinessProbe
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
  - 0.4
  - 0.1
  - 1.9
  - 0.6
  - 0.7
  - 0.5
  - 0.7
window_s: 76
EXERCISED:
  - "[[Service/cart]]"
---
