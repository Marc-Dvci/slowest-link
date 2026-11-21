---
type: Test
affected:
  - Place an order
date: 2026-11-14
fault: paymentFailure
kind: flag
name: 2026-11-14 flag_paymentFailure
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
  - 1.0
  - 2.0
  - 0.4
  - 0.6
  - 0.4
  - 0.5
window_s: 76
EXERCISED:
  - "[[Service/payment]]"
---
