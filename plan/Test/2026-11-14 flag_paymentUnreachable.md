---
type: Test
affected:
  - Place an order
date: 2026-11-14
fault: paymentUnreachable
kind: flag
name: 2026-11-14 flag_paymentUnreachable
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
  - 0.3
  - 4.0
  - 0.9
  - 0.0
  - 0.8
  - 0.9
window_s: 76
EXERCISED:
  - "[[Service/payment]]"
---
