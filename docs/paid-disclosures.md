# Paid disclosures (Paid 1.0)

Short disclosure contract for paid catalogue checkout, Packs, and Settings.
Site pages on [krellbot.dev](https://krellbot.dev) should stay consistent with
this file. The workstation surfaces the same facts under **Packs** and
**Home → Settings → Paid disclosures**. Do not invent a second story.

Owner legal copy, processor account, price, and final refund-window terms
remain an owner gate (`docs/milestones/M21.md` M21.6). Agents never process
real charges in CI — fake processors only. `PAPER_ONLY_RELEASE` stays True
until an explicit owner flip.

## Disclosures

1. **Fee share / referral.** When fee share or referral attribution is
   shown, it uses the disclosed earn rule: exchange **fee share / referral**
   when an operator creates or links an exchange account through a Krellbot
   referral path (`docs/product-direction.md`). Pack purchases may include
   disclosed attribution under that rule. See Settings → Exchange fee share /
   referral.

2. **Packs are not personalized advice.** Paid and free packs are tools —
   **not personalized advice**. Fixture and backtest results stay labeled
   and are never live market performance. **No returns promises.**

3. **Refund window pointer.** Request a pack refund from Packs (catalogue
   SKU → refund request). On success the local entitlement is revoked and
   journaled; billing failure cannot block exits or export. The refund path
   and refund-window pointer live in [refunds.md](refunds.md). Owner-set
   refund-window terms are recorded at M21.6 — this page only points there.

4. **Telemetry opt-in.** Telemetry stays **opt-in** (default off). Enable
   only with an explicit operator choice; payloads never carry keys,
   secrets, or strategy source. See [telemetry.md](telemetry.md).

## Where it appears

| Surface | What shows |
| --- | --- |
| Packs | Fee share / referral line when shown; honesty that packs are not personalized advice; refund window pointer; telemetry opt-in; link to this page |
| Settings (Home) | Same closed disclosure copy + links to this page, refunds, and telemetry |
| Site / docs | This file is the site disclosure source of truth |

## Related

- Launch pack family honesty: [launch-pack-family.md](launch-pack-family.md)
- Refund path: [refunds.md](refunds.md)
- Telemetry: [telemetry.md](telemetry.md)
- Product earn rules: [product-direction.md](product-direction.md)
