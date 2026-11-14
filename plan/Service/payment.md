---
type: Service
description: Payment service that charges the customer's card.
name: payment
owner: Payments
recovery_min: 30
CALLS:
  - calls: 4
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
