# Jupiter Portfolio via persistent Chromium

Use this when the weekly portfolio informer must collect Solana/Jupiter data and Camofox/browser snapshots show `Checking that you are a human`, generic marketing/login text, or an empty DOM.

## Durable lesson

Jupiter Portfolio can render normally in the user's persistent Chromium profile while failing or returning verification/empty text in Camofox. For the weekly informer, Solana data should be read from `https://jup.ag/portfolio/<solana-address>` through a normal Chromium process under `xvfb-run`, while EVM/DeBank can remain on Camofox.

## Implementation pattern

- Use a persistent Chromium profile, e.g. `<persistent-browser-profile>`, so already-passed Jupiter/browser checks survive cron runs.
- Launch Chromium under `xvfb-run` with a remote debugging port, then read the page through CDP.
- Remove `DBUS_SESSION_BUS_ADDRESS` from the Chromium subprocess environment before launch; in the Telegram/cron environment it can cause headed Chromium under xvfb to open an empty page.
- Prefer the Hermes agent venv Python in the shell wrapper if the CDP reader depends on Python packages such as `websockets`.
- Keep the wait long enough for Jupiter widgets; 15 seconds is a safer default than 5 seconds.

## Reporting rule

Do not hide a failed Jupiter read by sending only native SOL balance from RPC. Jupiter includes DeFi, staked, claimable, and protocol sections; RPC-only output is incomplete and misleading for the user's intended weekly report.

If Chromium cannot read Jupiter `Net Worth`, report Solana/Jupiter as not verified/readable and include the failure/checklist at the end of the report.

## Useful verification checklist

1. Compile the informer script:
   - `python3 -m py_compile scripts/chro-informer.py`
2. Run the wrapper dry-run:
   - `./scripts/run-chro-informer.sh --dry-run`
3. Confirm the message contains:
   - `Solana / Jupiter`
   - `net worth`
   - protocol sections such as `Validators`, `Orca`, `Kamino`, `Jupiter DAO` when visible
   - per-wallet share percentages in the summary
4. If Camofox tab limits affect EVM collection, close the weekly group and retry:
   - `curl -sS -X DELETE http://127.0.0.1:<browser-service-port>/tabs/group/weekly-informer -H 'content-type: application/json' -d '{"userId":"portfolio-review"}'`
