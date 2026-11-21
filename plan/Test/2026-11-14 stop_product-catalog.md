---
type: Test
affected:
  - Add to cart
  - Place an order
  - Show recommendations
  - View a product
date: 2026-11-14
fault: product-catalog
kind: stop
name: 2026-11-14 stop_product-catalog
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
  - 0.8
  - 0.5
  - 0.4
  - 7.2
  - 0.3
  - 0.3
window_s: 60
EXERCISED:
  - "[[Service/product-catalog]]"
---
