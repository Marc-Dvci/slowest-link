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
fault: frontend-proxy
kind: stop
name: 2026-11-14 stop_frontend-proxy
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
  - 10.8
  - 10.8
  - 10.7
  - 10.8
  - 10.8
  - 10.8
  - 10.8
window_s: 60
EXERCISED:
  - "[[Service/frontend-proxy]]"
---
