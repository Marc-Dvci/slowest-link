---
type: Service
description: Product catalogue service that lists products and their prices.
name: product-catalog
owner: Catalogue
recovery_min: 30
CALLS:
  - calls: 1305
    declared: true
    journeys:
      - Add to cart
      - Place an order
      - Show recommendations
      - View a product
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: ""
    source: published architecture
    target: "[[Datastore/astronomy-db]]"
  - declared: true
    mode: unknown
    observed: false
    protocol: gRPC
    source: published architecture
    target: "[[Service/flagd]]"
---
