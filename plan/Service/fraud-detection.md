---
type: Service
description: Fraud detection service that screens each placed order.
name: fraud-detection
owner: Risk
recovery_min: 120
CALLS:
  - calls: 154
    declared: true
    journeys:
      - Screen orders for fraud
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: TCP
    source: published architecture
    target: "[[Queue/kafka]]"
  - calls: 2
    declared: true
    journeys:
      - Screen orders for fraud
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    survival_tests:
      - 2026-11-14 stop:flagd
    survives_without:
      - Screen orders for fraud
    target: "[[Service/flagd]]"
---
