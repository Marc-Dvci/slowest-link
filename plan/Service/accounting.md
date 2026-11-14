---
type: Service
description: Accounting service that records each placed order in the ledger.
name: accounting
owner: Finance
recovery_min: 120
CALLS:
  - calls: 79
    declared: true
    journeys:
      - Record orders in accounting
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: ""
    source: published architecture
    target: "[[Datastore/astronomy-db]]"
  - calls: 78
    declared: true
    journeys:
      - Record orders in accounting
    mode: sync
    observed: true
    observed_on: 2026-11-14
    protocol: TCP
    source: published architecture
    target: "[[Queue/kafka]]"
---
