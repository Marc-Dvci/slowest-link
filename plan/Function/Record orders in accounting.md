---
type: Function
critical: true
description: Each placed order is written to the ledger.
journeys: []
name: Record orders in accounting
promise_min: 1440
ENTERS:
  - "[[Service/accounting]]"
USES:
  - "[[Datastore/astronomy-db]]"
  - "[[Service/accounting]]"
---
