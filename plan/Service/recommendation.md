---
type: Service
description: Recommendation service that suggests related products.
name: recommendation
owner: Marketing
recovery_min: 60
CALLS:
  - declared: true
    mode: unknown
    observed: false
    protocol: gRPC
    source: published architecture
    target: "[[Service/flagd]]"
  - calls: 86
    declared: true
    journeys:
      - Show recommendations
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/product-catalog]]"
---
