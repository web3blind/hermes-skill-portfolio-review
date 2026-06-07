# Portfolio informer debugging notes

Use when the weekly portfolio informer sends a strange or low-value message (for example only `Withdraw` / `Claim`, missing totals, missing allocation percentages, or generic Jupiter marketing text).

## Durable workflow

1. Inspect the cron job and last output first:
   - identify the `portfolio-informer-weekly` job;
   - read the latest `~/.hermes/cron/output/<job_id>/*.md`;
   - compare it with a dry run of `~/.hermes/scripts/hermes_portfolio_chro_informer.sh --dry-run --pretty`.
2. Backup before changing the skill script or wrapper.
3. Verify Camofox health before blaming the parser.
4. DeBank accessibility snapshots often contain useful data as merged lines, not neat rows:
   - profile header line can contain `... $12,433 -1.05%` → parse this as wallet total + daily change;
   - chain allocation can be a single line like `Ethereum $302 42% Arbitrum $191 26% Hyperliquid $97` → parse compact name/value/percent groups;
   - token rows often appear as `SYMBOL` followed by one merged line like `$1.0011 135.3807 $135.53` → last money value is USD value;
   - protocol blocks often expose a protocol name in preceding lines and a value line containing `Yield`, `Staked`, `Deposit`, `Pool`, etc.
5. Keep the output fact-first:
   - total readable net worth;
   - per-wallet share percentage;
   - per-wallet total/change, chain allocation, top tokens, DeFi/protocols;
   - short assessment and recommendations after the facts.
6. Do not treat Jupiter marketing/login/human-verification text or an empty DOM as portfolio data. For the automated weekly informer, do **not** send a native-SOL RPC fallback as if it were the Solana portfolio; that misses Jupiter-visible DeFi/staked/claimable positions. Prefer the dedicated Chromium+xvfb Jupiter path, and if it cannot read `Net Worth`, say Solana/Jupiter could not be verified.
7. Increase page wait time when browser-visible DeBank/Jupiter data is incomplete; 5 seconds is often too short, 15 seconds was a better default in this case.
8. Watch Camofox tab accumulation for the weekly informer group. If tab creation fails or Camofox has many stale `weekly-informer` tabs, close the group and retry rather than degrading the report.
9. Validate with `python3 -m py_compile <script>` and a dry-run before letting the scheduled cron deliver.

## Privacy rule

Do not store raw wallet addresses, balances, totals, token amounts, percentages, or raw page text in informer state. It should remain hash/timestamp/decision metadata only.
