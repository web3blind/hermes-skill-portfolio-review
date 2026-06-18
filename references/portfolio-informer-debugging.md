# Portfolio informer debugging notes

Use when the weekly portfolio informer sends a strange or low-value message (for example only `Withdraw` / `Claim`, missing totals, missing allocation percentages, or generic Jupiter marketing text).

## Durable workflow

1. Inspect the cron job and last output first:
   - identify the `portfolio-informer-weekly` job;
   - read the latest cron artifact for the portfolio informer job;
   - compare it with a dry run of the portfolio informer wrapper, for example `hermes_portfolio_chro_informer.sh --dry-run --pretty`.
2. Backup before changing the skill script or wrapper.
3. Verify Camofox health before blaming the parser.
4. DeBank accessibility snapshots often contain useful data as merged lines, not neat rows:
   - profile header line can contain `... $12,433 -1.05%` → parse this as wallet total + daily change;
   - chain allocation can be a single line like `Ethereum $302 42% Arbitrum $191 26% Hyperliquid $97` → parse compact name/value/percent groups;
   - token rows often appear as `SYMBOL` followed by one merged line like `$1.0011 135.3807 $135.53` → last money value is USD value;
   - protocol blocks often expose a protocol name in preceding lines and a value line containing `Yield`, `Staked`, `Deposit`, `Pool`, etc.
5. Keep the output fact-first:
   - total readable net worth;
   - per-wallet share percentage only when every source has a readable net worth;
   - if any source lacks net worth, mark the aggregate incomplete and do not compute concentration, protocol %, stable %, or misleading "100% of portfolio" shares from the partial denominator;
   - per-wallet total/change, chain allocation, top tokens, DeFi/protocols;
   - short assessment and recommendations after the facts.
6. Do not treat Jupiter marketing/login/human-verification text or an empty DOM as portfolio data. For the automated weekly informer, do **not** send a native-SOL RPC fallback as if it were the Solana portfolio; that misses Jupiter-visible DeFi/staked/claimable positions. Prefer the dedicated Chromium+xvfb Jupiter path, and if it cannot read `Net Worth`, say Solana/Jupiter could not be verified.
7. Increase page wait time when browser-visible DeBank/Jupiter data is incomplete; 5 seconds is often too short, 15 seconds was a better default in this case. For Jupiter, if the first Chromium read contains the app shell but no `Net Worth`, retry once with a longer fresh Chromium read before marking Solana missing.
8. Preserve negative money signs in parser cleanup. Do not strip a leading `-` from lines like `-$44.99`; only strip list bullets with `^-\s+`, otherwise PnL and period changes become falsely positive.
9. Watch Camofox tab accumulation/staleness for the weekly informer group. DeBank can return a false-empty shell (`Data updated ...`, `All Chain`, `No assets yet`) for non-empty wallets when a stale `weekly-informer` tab group is reused. Start each run by closing the group, and if a DeBank item has no parsed total plus `No assets yet`, close the group and retry once with a longer wait rather than degrading the report.
10. Validate with `python3 -m py_compile <script>` and multiple dry-runs before letting the scheduled cron deliver.

## Privacy rule

Do not store raw wallet addresses, balances, totals, token amounts, percentages, or raw page text in informer state. It should remain hash/timestamp/decision metadata only.
