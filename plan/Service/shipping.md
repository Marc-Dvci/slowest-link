---
type: Service
description: Shipping service that quotes shipping costs and ships orders.
name: shipping
owner: Orders
recovery_min: 30
CALLS:
  - declared: true
    mode: unknown
    observed: false
    protocol: gRPC
    source: published architecture
    target: "[[Service/flagd]]"
  - calls: 134
    declared: true
    journeys:
      - Place an order
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: HTTP
    source: published architecture
    target: "[[Service/quote]]"
---
