---
type: Test
affected:
  - Place an order
  - Record orders in accounting
  - Screen orders for fraud
date: 2026-11-14
fault: kafka
kind: stop
name: 2026-11-14 stop_kafka
not_recovered:
  - user_checkout_single
recovery_journeys:
  - user_add_to_cart
  - user_browse_product
  - user_get_ads
  - user_get_recommendations
  - user_index
  - user_view_cart
recovery_s:
  - 0.9
  - 0.9
  - 0.9
  - 0.1
  - 0.9
  - 0.9
window_s: 60
EXERCISED:
  - "[[Queue/kafka]]"
---
