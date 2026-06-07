# Hermes Camofox portfolio informer notes

Use this when maintaining the browser-dependent portfolio informer for DeBank/Jupiter.

## Stable pattern

- Keep screenshot/manual review separate from automated browser collection.
- Use Hermes Camofox HTTP service (`CAMOFOX_URL`, default `http://127.0.0.1:9377`) instead of legacy legacy agent `/chro` or `chromium-manager.sh`.
- For recurring cron, prefer a script-only wrapper that prints either a useful short message or `NO_REPLY` when nothing materially changed.
- Keep state privacy-preserving: hashes, timestamps, and decision metadata only. Do not persist wallet addresses, balances, token amounts, raw holdings, or raw page snapshots.

## Camofox tab/session pitfalls

- Reusing the same `userId` + `sessionKey` can hit service session tab limits after test runs or failed attempts.
- A robust informer should either:
  - use a fresh run-scoped `userId`/`sessionKey`, or
  - create one tab and navigate it sequentially through all wallet URLs.
- For Jupiter Portfolio specifically, prefer a stable Camofox `userId`/`sessionKey` plus one sequentially navigated tab, so one-time Cloudflare/Jupiter human verification can persist in that browser profile.
- Avoid opening one new tab per wallet with the same long-lived session key; it can fail with `Maximum tabs per session reached`.
- When snapshots include accessibility-tree noise (`link`, `url`, truncated addresses), filter service/UI lines and address-like strings before hashing and summarizing.
- If Jupiter shows `Verification required to view your portfolio`, do **not** replace the portfolio with a misleading RPC-only SOL balance. Report that Solana/Jupiter data is blocked until the persistent browser profile passes verification; only include Solana in totals when Jupiter’s Net Worth / token / DeFi sections are visible.

## Verification checklist

1. `python3 -m py_compile <informer.py>`.
2. `bash -n <wrapper.sh>` and `chmod +x` / restrictive executable permissions.
3. Dry-run with a short wait and no delivery.
4. Confirm the output covers all configured wallets, not just the first reused tab.
5. Search the skill for legacy browser-manager references before enabling cron.
