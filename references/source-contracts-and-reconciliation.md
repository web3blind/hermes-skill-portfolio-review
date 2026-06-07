# Source Contracts and Reconciliation

Use this when maintaining the portfolio-review skill, parser, or informer. The goal is to stop a browser snapshot from turning into a confident but wrong portfolio report.

## Source hierarchy

Prefer sources in this order:

1. **Direct exchange / protocol / chain reads** for venues where the portfolio logic has a reliable adapter.
2. **Fresh browser-visible portfolio pages** such as DeBank for EVM and Jupiter Portfolio for Solana.
3. **Explorer or RPC identity checks** for token names, contracts, staking wrappers, and disputed rows.
4. **Last-good snapshot** only as degraded fallback, never as a clean current report.

Rules:

- A visible DeBank/Jupiter row is a discovery signal, not always final truth.
- If two sources disagree materially, mark the row as `needs verification` instead of forcing it into the total.
- Do not use a native-balance-only RPC fallback as a replacement for portfolio pages; it hides DeFi, staked, wrapped, and claimable positions.

## Row contract

Every material row that enters a final report should have:

```json
{
  "source": "debank|jupiter|rpc|explorer|direct-protocol|last-good",
  "wallet_key_hash": "privacy-safe wallet key hash",
  "chain": "chain/network name",
  "label": "human-readable token or protocol label",
  "kind": "liquid|defi|staked|claimable|liability|audit-only",
  "amount_visible": "optional human amount, only if safe for the output",
  "usd_value": 123.45,
  "fresh_at": "ISO-8601 timestamp",
  "verification": "fresh|stale|disputed|needs-verification"
}
```

For public/exported skills, keep wallet addresses and raw page text out of durable state. Use hashes and short labels for correlation.

## Accounting invariants

Before returning a review or informer message:

- `total ~= liquid + defi + staked + claimable - liabilities` within rounding.
- Protocol rows and their wallet-token wrappers must not both be counted.
- Perp notional exposure is not spot portfolio value; separate exposure from holdings.
- Loans/liabilities subtract from value; they do not appear as assets.
- Dust can be aggregated, but the total must explain whether dust is included.
- A disputed provider/browser row is audit-only until verified.

## Freshness policy

Use concise freshness labels:

```text
fresh: DeBank 4m · Jupiter 7m
stale: Jupiter 2d — Solana DeFi may be incomplete
```

If a material source is stale or failed, say `degraded` or `needs verification`. Do not present a clean-looking total when the source mix is incomplete.

## Correction registry

When a row is known to be duplicated, stale, renamed, or misclassified, represent the fix as data/rules rather than scattered string hacks.

Minimum public-safe shape:

```json
{
  "match": {"source": "debank", "label_regex": "Wrapped Example"},
  "action": "suppress|rename|reclassify|merge|audit-only",
  "target": "Example Protocol",
  "reason": "duplicates protocol row / stale provider row / direct verification",
  "status": "verified|manual-confirmed|provider-only",
  "created_at": "YYYY-MM-DD"
}
```

Keep private wallet identifiers out of the public registry. If a correction is wallet-specific, store a wallet key hash or document the pattern without exposing the address.

## Output guardrails

Normal user-facing output should not leak implementation noise:

- no raw source suffixes in every row;
- no debug dumps or browser accessibility-tree lines;
- no raw wallet addresses unless the user explicitly asked for them;
- no unknown labels like `TOKEN <id>` or `Asset` in final rows;
- no confident recommendation when the row is stale, disputed, or source-only.

A good report separates:

1. visible facts;
2. accounting / freshness issues;
3. candidate actions;
4. missing verification;
5. one next step.
