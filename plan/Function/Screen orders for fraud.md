---
type: Function
critical: false
description: Each placed order is screened for fraud.
journeys: []
name: Screen orders for fraud
promise_min: 240
ENTERS:
  - "[[Service/fraud-detection]]"
USES:
  - "[[Service/fraud-detection]]"
---
