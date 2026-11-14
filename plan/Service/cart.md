---
type: Service
description: Cart service that stores each visitor's shopping cart.
name: cart
owner: Storefront
recovery_min: 30
CALLS:
  - calls: 1235
    declared: true
    journeys:
      - Add to cart
      - Place an order
      - View cart
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: ""
    source: published architecture
    target: "[[Datastore/valkey-cart]]"
  - calls: 201
    declared: true
    journeys:
      - Place an order
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/flagd]]"
---
