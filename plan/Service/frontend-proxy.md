---
type: Service
description: Envoy front door that routes every web request to the frontend, images and feature flags.
name: frontend-proxy
owner: Platform
recovery_min: 15
CALLS:
  - declared: true
    mode: unknown
    observed: false
    protocol: gRPC
    source: published architecture
    target: "[[Service/flagd]]"
  - declared: true
    mode: unknown
    observed: false
    protocol: HTTP
    source: published architecture
    target: "[[Service/flagd-ui]]"
  - calls: 1372
    declared: true
    journeys:
      - Add to cart
      - Browse the shop
      - Place an order
      - Show ads
      - Show recommendations
      - View a product
      - View cart
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: HTTP
    source: published architecture
    target: "[[Service/frontend]]"
  - declared: true
    mode: unknown
    observed: false
    protocol: HTTP
    source: published architecture
    target: "[[Service/image-provider]]"
---
