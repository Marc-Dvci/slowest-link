---
type: Service
description: Next.js web frontend that renders the shop pages and serves its API routes.
name: frontend
owner: Storefront
recovery_min: 15
CALLS:
  - calls: 242
    declared: true
    journeys:
      - Show ads
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/ad]]"
  - calls: 1140
    declared: true
    journeys:
      - Add to cart
      - Place an order
      - View cart
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/cart]]"
  - calls: 134
    declared: true
    journeys:
      - Place an order
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/checkout]]"
  - declared: true
    mode: unknown
    observed: false
    protocol: gRPC
    source: published architecture
    target: "[[Service/currency]]"
  - calls: 2172
    declared: true
    journeys:
      - Add to cart
      - Place an order
      - Show recommendations
      - View a product
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/product-catalog]]"
  - calls: 175
    declared: true
    journeys:
      - Show recommendations
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/recommendation]]"
  - declared: true
    mode: unknown
    observed: false
    protocol: HTTP
    source: published architecture
    target: "[[Service/shipping]]"
---
