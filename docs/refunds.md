# Pack refund path

Local paid catalogue SKUs granted through the live checkout seam can be
disabled through a **refund request** on the Packs surface.

## What a refund request does

1. The workstation POSTs the catalogue SKU to
   ``/api/v1/checkout/refund`` (session + CSRF + loopback Origin).
2. An injectable payment transport asks the cloud processor to refund.
   Tests use a fake processor only — no real processor keys ship in the
   repo.
3. On success the local SKU entitlement is **revoked** (removed from
   ``catalog/sku-entitlements.json``), the purchased catalog row is
   dropped, the checkout claim cache is cleared, and a journal audit
   row is appended:

   - ``kind``: ``entitlement``
   - ``detail.event``: ``entitlement_revoked``
   - ``detail.source``: ``refund``

4. On transport failure the entitlement, license cache, armed config,
   and export paths are left untouched. Billing failure must not block
   exits or historical export (`docs/product-direction.md`).

Refunds disable **local SKU entitlement** only. They do not rewrite the
global license cache and are not personalized advice or a returns
promise. Owner legal copy, processor account, and refund-window terms
remain an owner gate (M21.6).
