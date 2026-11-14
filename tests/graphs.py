"""Small graphs for the tests, built with the same Cypher shapes the seed and the trace import write."""

from __future__ import annotations

import relate

# A shop in miniature. Two web functions enter at the proxy; one back-office function enters at the consumer.
#
#   proxy(15) -> web(15) -> catalog(30) -> db(240)        View product, Place order
#                web     -> orders(30)  -> catalog                      Place order
#                           orders      -> mail(60)        soft for Place order once a test proves it
#                           orders      ~> queue(120)      async
#   ledger(120) -> queue, ledger -> db                    Record orders
#   web -> ads(60), declared but never observed
#   db -> proxy: an observed call no one declared (a cycle the paths must not loop on)
MINI_SHOP = """
CREATE (view:Function {name: 'View product', promise_min: 60, critical: true, journeys: ['user_view']}),
       (order:Function {name: 'Place order', promise_min: 60, critical: true, journeys: ['user_order']}),
       (record:Function {name: 'Record orders', promise_min: 1440, critical: true, journeys: []}),
       (ads_f:Function {name: 'Show ads', promise_min: 30, critical: false, journeys: ['user_ads']}),
       (proxy:Service {name: 'proxy', recovery_min: 15, description: 'front door'}),
       (web:Service {name: 'web', recovery_min: 15, description: 'web frontend'}),
       (catalog:Service {name: 'catalog', recovery_min: 30, description: 'product catalogue'}),
       (orders:Service {name: 'orders', recovery_min: 30, description: 'checkout of orders'}),
       (mail:Service {name: 'mail', recovery_min: 60, description: 'confirmation email'}),
       (ads:Service {name: 'ads', recovery_min: 60, description: 'contextual ads'}),
       (ledger:Service {name: 'ledger', recovery_min: 120, description: 'accounting ledger writer'}),
       (db:Datastore {name: 'db', recovery_min: 240, description: 'PostgreSQL database for the catalogue'}),
       (queue:Queue {name: 'queue', recovery_min: 120, description: 'Kafka message queue'}),
       (view)-[:ENTERS]->(proxy), (order)-[:ENTERS]->(proxy), (record)-[:ENTERS]->(ledger), (ads_f)-[:ENTERS]->(proxy),
       (view)-[:USES]->(proxy), (view)-[:USES]->(web), (view)-[:USES]->(catalog),
       (order)-[:USES]->(proxy), (order)-[:USES]->(web), (order)-[:USES]->(orders),
       (record)-[:USES]->(ledger),
       (ads_f)-[:USES]->(proxy), (ads_f)-[:USES]->(web), (ads_f)-[:USES]->(ads),
       (proxy)-[:CALLS {declared: true, observed: true, mode: 'sync',
                        journeys: ['View product', 'Place order']}]->(web),
       (web)-[:CALLS {declared: true, observed: true, mode: 'sync', journeys: ['View product']}]->(catalog),
       (web)-[:CALLS {declared: true, observed: true, mode: 'sync', journeys: ['Place order']}]->(orders),
       (web)-[:CALLS {declared: true, observed: false, mode: 'unknown'}]->(ads),
       (orders)-[:CALLS {declared: true, observed: true, mode: 'sync', journeys: ['Place order']}]->(catalog),
       (orders)-[:CALLS {declared: true, observed: true, mode: 'sync', journeys: ['Place order']}]->(mail),
       (orders)-[:CALLS {declared: true, observed: true, mode: 'async', journeys: ['Place order']}]->(queue),
       (catalog)-[:CALLS {declared: true, observed: true, mode: 'sync',
                          journeys: ['View product', 'Place order']}]->(db),
       (ledger)-[:CALLS {declared: true, observed: true, mode: 'sync', journeys: ['Record orders']}]->(queue),
       (ledger)-[:CALLS {declared: true, observed: true, mode: 'sync', journeys: ['Record orders']}]->(db),
       (db)-[:CALLS {declared: false, observed: true, mode: 'sync', journeys: ['View product'],
                     source: 'traces'}]->(proxy)
"""


def mini_shop() -> relate.Connection:
    conn = relate.connect(":memory:")
    conn.execute(MINI_SHOP)
    conn.execute(
        "CREATE FULLTEXT INDEX component_text IF NOT EXISTS FOR (n:Service|Datastore|Queue) "
        "ON EACH [n.name, n.description]"
    )
    return conn
