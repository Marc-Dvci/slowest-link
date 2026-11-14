# A coding agent and the plan guard hook

A real session, 14 November 2026: Claude Code, run headless in a clone of this repository with its
[`.claude/settings.json`](../.claude/settings.json) hook, was asked:

> We are adding featured products to the home page, so the frontend now calls product-catalog when a customer browses
> the shop. Record this in the continuity plan: in plan/Service/frontend.md, add 'Browse the shop' to the journeys of
> the frontend -> product-catalog call.

The agent's edit:

```diff
diff --git a/plan/Service/frontend.md b/plan/Service/frontend.md
index 8016dcb..f4dc49f 100644
--- a/plan/Service/frontend.md
+++ b/plan/Service/frontend.md
@@ -47,6 +47,7 @@ CALLS:
     declared: true
     journeys:
       - Add to cart
+      - Browse the shop
       - Place an order
       - Show recommendations
       - View a product
```

The hook ran the guard against `HEAD` after the edit and returned:

```text
Change: plan change: frontend -> product-catalog for Browse the shop
NEW    Browse the shop: promises 1 h, slowest link 4 h
       frontend-proxy -> frontend -> product-catalog -> astronomy-db
NEW    Browse the shop: promises 1 h, restore chain 5 h
       frontend-proxy -> frontend -> product-catalog -> astronomy-db
```

The agent answered (excerpt):

> I've added "Browse the shop" to the journeys of the frontend → product-catalog call in `plan/Service/frontend.md`. Nothing is committed. Once the change is in the plan, it shows that **Browse the shop can no longer meet its recovery promise** (evidence view).
>
> Your post-edit hook ran it right after the change and reported two new findings:
>
> | Function | Promise | Finding | Path |
> |---|---|---|---|
> | Browse the shop | 1 h | slowest link 4 h | frontend-proxy → frontend → product-catalog → astronomy-db |
> | Browse the shop | 1 h | restore chain 5 h | frontend-proxy → frontend → product-catalog → astronomy-db |
>
> So adding featured products makes browsing the shop wait on product-catalog and its database, astronomy-db. The 4 h figure is the slowest single component on that path. The 5 h figure is the restore chain: how long it takes to bring the whole path back in order. Both are well past the 1 h promise.
>
> - **Make the call non-blocking for this journey:** load featured products asynchronously and render the home page without them if the catalog is down. Then run an outage test so the plan can record that Browse the shop survives without the call.
> - **Change the numbers:** relax the 1 h promise on Browse the shop, or have the product-catalog / astronomy-db owners commit to faster recovery. Both are edits to notes in `plan/` that a person should review.
> - **Keep the edit as is and accept the finding** until one of those is done.
