# Results

Every number on this page is computed from the files in [`evidence/`](../evidence/) and the plan
vault by [`experiments/results_report.py`](../experiments/results_report.py).

## Traces (E0)

- 1037 traces, 1037 attributed to a function of the plan.
- 24 calls between components observed; 24 of them are in the published architecture and 0 are not.
- 10 declared calls appear in no trace: checkout -> flagd, email -> flagd, frontend -> currency, frontend -> shipping, frontend-proxy -> flagd, frontend-proxy -> flagd-ui, frontend-proxy -> image-provider, product-catalog -> flagd, recommendation -> flagd, shipping -> flagd.

## Findings on the plan

| View | Broken promises | Restore chains past the promise |
|---|---|---|
| Plan | 0: none | 0: none |
| Architecture | 5: Add to cart, Browse the shop, Place an order, View a product, View cart | 5: Add to cart (6 h), Browse the shop (6 h), Place an order (6 h), View a product (6 h), View cart (6 h) |
| Evidence | 3: Add to cart, Place an order, View a product | 4: Add to cart (5 h), Place an order (5 h 30 min), View a product (5 h), View cart (1 h 30 min) |

Dependencies the plan's own list leaves out (evidence view):

- Add to cart: astronomy-db (4 h), valkey-cart (30 min)
- Place an order: astronomy-db (4 h), kafka (2 h), product-catalog (30 min), quote (30 min), valkey-cart (30 min), flagd (15 min)
- Record orders in accounting: kafka (2 h)
- Screen orders for fraud: kafka (2 h)
- Show ads: flagd (15 min)
- Show recommendations: astronomy-db (4 h), product-catalog (30 min)
- View a product: astronomy-db (4 h)
- View cart: valkey-cart (30 min)

## Outage tests (E1 and E2)

Predictions were committed before the tests ran. A pair is one fault and one function; back-office
functions are left out of a test when no order was placed in its window.

### Stopping each component for 60 seconds (E1)

| View | Outages predicted | False alarms | Precision | Recall | Tests exactly right |
|---|---|---|---|---|---|
| Plan | 25 of 40 | 3 | 89% | 62% | 11 of 20 |
| Architecture | 40 of 40 | 91 | 30% | 100% | 2 of 20 |
| Evidence | 39 of 40 | 4 | 91% | 98% | 15 of 20 |

| Fault | Functions measured down | Plan | Architecture | Evidence |
|---|---|---|---|---|
| accounting | none | 1 wrong | 1 wrong | 1 wrong |
| ad | Show ads | right | 6 wrong | right |
| cart | Add to cart, Place an order, View cart | right | 4 wrong | right |
| checkout | Place an order | right | 6 wrong | right |
| currency | Place an order | right | 6 wrong | right |
| email | none | 1 wrong | 7 wrong | 1 wrong |
| flagd | Place an order, Show ads | 2 wrong | 6 wrong | 1 wrong |
| flagd-ui | none | right | 7 wrong | right |
| fraud-detection | none | 1 wrong | 1 wrong | 1 wrong |
| frontend | Add to cart, Browse the shop, Place an order, Show ads, Show recommendations, View a product, View cart | right | right | right |
| frontend-proxy | Add to cart, Browse the shop, Place an order, Show ads, Show recommendations, View a product, View cart | right | right | right |
| image-provider | none | right | 7 wrong | right |
| kafka | Place an order, Record orders in accounting, Screen orders for fraud | 3 wrong | 6 wrong | 1 wrong |
| payment | Place an order | right | 6 wrong | right |
| product-catalog | Add to cart, Place an order, Show recommendations, View a product | 2 wrong | 3 wrong | right |
| quote | Place an order | 1 wrong | 6 wrong | right |
| recommendation | Show recommendations | right | 6 wrong | right |
| shipping | Place an order | right | 6 wrong | right |
| valkey-cart | Add to cart, Place an order, View cart | 3 wrong | 4 wrong | right |
| astronomy-db | Add to cart, Place an order, Show recommendations, View a product | 4 wrong | 3 wrong | right |

### Turning on each failure flag for 76 seconds (E2)

| View | Outages predicted | False alarms | Precision | Recall | Tests exactly right |
|---|---|---|---|---|---|
| Plan | 5 of 9 | 12 | 29% | 56% | 6 of 14 |
| Architecture | 9 of 9 | 92 | 9% | 100% | 0 of 14 |
| Evidence | 9 of 9 | 16 | 36% | 100% | 5 of 14 |

| Fault | Functions measured down | Plan | Architecture | Evidence |
|---|---|---|---|---|
| adFailure | none | 1 wrong | 7 wrong | 1 wrong |
| adHighCpu | none | 1 wrong | 7 wrong | 1 wrong |
| adManualGc | Show ads | right | 6 wrong | right |
| cartFailure | Place an order | 2 wrong | 6 wrong | 2 wrong |
| emailMemoryLeak | none | 1 wrong | 7 wrong | 1 wrong |
| failedReadinessProbe | none | 3 wrong | 7 wrong | 3 wrong |
| imageSlowLoad | none | right | 7 wrong | right |
| intlShippingSlowdown | Place an order | right | 6 wrong | right |
| kafkaQueueProblems | none | right | 9 wrong | 2 wrong |
| paymentFailure | Place an order | right | 6 wrong | right |
| paymentUnreachable | Place an order | right | 6 wrong | right |
| productCatalogFailure | none | 2 wrong | 7 wrong | 4 wrong |
| productCatalogLockContention | Add to cart, Place an order, Show recommendations, View a product | 5 wrong | 4 wrong | 1 wrong |
| recommendationCacheFailure | none | 1 wrong | 7 wrong | 1 wrong |

Measured recovery after a restart, over 37 affected journeys: longest 10.9 s (user_checkout_single after cart).

Stop tests that left a journey down until the services were restarted:

- kafka: user_checkout_single
