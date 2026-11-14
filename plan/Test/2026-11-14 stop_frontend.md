---
type: Test
affected:
  - Add to cart
  - Browse the shop
  - Place an order
  - Show ads
  - Show recommendations
  - View a product
  - View cart
date: 2026-11-14
fault: frontend
kind: stop
name: 2026-11-14 stop:frontend
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
  - 1.2
  - 1.2
  - 2.2
  - 1.2
  - 1.2
  - 1.2
  - 1.2
window_s: 60
EXERCISED:
  - "[[Service/frontend]]"
---
