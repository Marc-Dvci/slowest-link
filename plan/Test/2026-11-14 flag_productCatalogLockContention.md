---
type: Test
affected:
  - Add to cart
  - Place an order
  - Show recommendations
  - View a product
date: 2026-11-14
fault: productCatalogLockContention
kind: flag
name: 2026-11-14 flag_productCatalogLockContention
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
  - 0.7
  - 0.6
  - 0.7
  - 0.4
  - 0.7
  - 0.2
  - 0.3
window_s: 76
EXERCISED:
  - "[[Datastore/astronomy-db]]"
---
