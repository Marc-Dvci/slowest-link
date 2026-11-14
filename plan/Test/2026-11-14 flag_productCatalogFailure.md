---
type: Test
affected: []
date: 2026-11-14
fault: productCatalogFailure
kind: flag
name: 2026-11-14 flag:productCatalogFailure
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
  - 0.5
  - 0.9
  - 0.3
  - 0.5
  - 0.7
  - 0.4
  - 0.5
window_s: 76
EXERCISED:
  - "[[Service/product-catalog]]"
---
