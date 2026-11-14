---
type: Service
description: Ad service that serves contextual ads.
name: ad
owner: Marketing
recovery_min: 60
CALLS:
  - calls: 6
    declared: true
    journeys:
      - Show ads
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: gRPC
    source: published architecture
    target: "[[Service/flagd]]"
---
