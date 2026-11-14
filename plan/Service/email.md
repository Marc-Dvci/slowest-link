---
type: Service
description: Email service that sends the order confirmation.
name: email
owner: Orders
recovery_min: 60
CALLS:
  - declared: true
    mode: unknown
    observed: false
    protocol: gRPC
    source: published architecture
    target: "[[Service/flagd]]"
---
