---
type: Service
description: |-
  Checkout service that places an order: cart, prices, payment, shipping and confirmation.
name: checkout
owner: Orders
recovery_min: 30
CALLS:
  - calls: 67
    declared: true
    journeys:
      - Place an order
    mode: async
    need_tests:
      - 2026-11-14 stop:kafka
    needed_by:
      - Place an order
    observed: true
    observed_on: 2026-11-14
    protocol: TCP
    source: published architecture
    target: "[[Queue/kafka]]"
  - calls: 134
    declared: true
    journeys:
      - Place an order
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/cart]]"
  - calls: 197
    declared: true
    journeys:
      - Place an order
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/currency]]"
  - calls: 134
    declared: true
    journeys:
      - Place an order
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: HTTP
    source: published architecture
    survival_tests:
      - 2026-11-14 stop:email
    survives_without:
      - Place an order
    target: "[[Service/email]]"
  - declared: true
    mode: unknown
    observed: false
    protocol: gRPC
    source: published architecture
    target: "[[Service/flagd]]"
  - calls: 67
    declared: true
    journeys:
      - Place an order
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/payment]]"
  - calls: 130
    declared: true
    journeys:
      - Place an order
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/product-catalog]]"
  - calls: 268
    declared: true
    journeys:
      - Place an order
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: HTTP
    source: published architecture
    target: "[[Service/shipping]]"
---
