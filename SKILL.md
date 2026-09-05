---
name: portfolio-review
description: Browser-first crypto portfolio review and weekly informer workflow using DeBank for EVM wallets and Jupiter Portfolio for Solana. Use when the user wants to review a crypto portfolio, inspect wallet allocation, compare visible DeFi/staked/claimable positions, or run a recurring portfolio informer without paid wallet APIs.
version: "1.1.0"
author: web3blind / Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [crypto, portfolio, wallet, browser, debank, jupiter, automation]
    category: finance
---
# Portfolio Review

## When to Use

Use this skill when the user wants to:

- review one or more crypto wallets;
- inspect visible DeFi, staking, claimable, or protocol positions;
- build a weekly/monthly portfolio informer;
- compare portfolio changes without storing raw balances or wallet data in state;
- troubleshoot DeBank/Jupiter browser extraction.

## Procedure

1. Confirm the review goal: quick review, full allocation review, thesis/rebalance review, or recurring informer.
2. Load wallet addresses from a local ignored file such as `addresses.conf`, or ask the user for addresses explicitly.
3. For EVM wallets, open `https://debank.com/profile/<address>` through the configured browser path.
4. For Solana wallets, open `https://jup.ag/portfolio/<address>` and collect visible Jupiter Portfolio data.
5. Extract the top summary first: total/net worth, chain/wallet split, top tokens, protocol positions, staked/claimable amounts, and visible PnL/change signals.
6. Do not replace Jupiter Portfolio with a native-SOL-only RPC fallback in automated reports. That hides DeFi/staked/claimable positions and creates false confidence.
7. Reconcile rows before trusting totals: protocol rows and their wallet-token wrappers must not both be counted; liabilities subtract from value; stale or disputed rows stay audit-only.
8. Return a compact, actionable review: facts, issues, candidate actions, missing information, and 1–2 decisions for the next review cycle.
9. For recurring jobs, store only privacy-safe state: hashes, timestamps, and decision metadata. Do not store raw wallet addresses, balances, token amounts, percentages, holdings, or page text.

## Lightweight manual review

When screenshots and brief notes already answer the question, review them directly before launching browser collection. Record visible facts, uncertainty, thesis changes, candidate actions, and missing data. A quick check should not automatically become a full multi-wallet investigation. Ask only for material missing inputs, such as the target allocation or comparison period.

## Freshness and accounting checks

- Confirm each browser tab shows the requested wallet before trusting its rows. A successful navigation call does not prove that the old wallet page has been replaced.
- Before computing allocation percentages, verify the denominator covers the same wallets, chains, positions, and observation period as the numerator. Never present an incomplete subtotal as the whole portfolio.
- Separate the source-reported total from the deduplicated reconciled subtotal. Unknown prices are unpriced, not zero; label partial coverage and avoid a precise total when a material component is unresolved.
- Deposits between a wallet and its pool/vault are internal movements, not income. Count fees only when identifiable, subtract liabilities, and include claimable rewards only when not already reflected in NAV.
- For yield wrappers and lending vaults, inspect underlying assets, curator/allocator authority, oracle and collateral risks, utilization, redemption terms, and actual exit liquidity. Displayed NAV or APR is not an executable exit quote.
- Recommendations are not authorization to connect a wallet, approve, sign, trade, deposit, or withdraw.

## Local Configuration

Create a local `addresses.conf` from the example:

```bash
cp addresses.example.conf addresses.conf
```

Format:

```conf
evm_example=0xYOUR_EVM_ADDRESS
sol_example=11111111111111111111111111111111
```

`addresses.conf`, state files, logs, and debug outputs are intentionally ignored by git.

## Source contracts

Use [`references/source-contracts-and-reconciliation.md`](references/source-contracts-and-reconciliation.md) when changing collectors or report logic. It defines source precedence, row contracts, stale/degraded reporting, correction-registry shape, and accounting invariants.

## Scripts

Primary public script:

```bash
python3 scripts/chro-informer.py --dry-run --pretty
python3 scripts/validate-public-export.py
```

If your environment uses a wrapper script, keep it outside the repository or document it without private paths.

## Pitfalls

- Browser-visible portfolio pages can merge totals, percentages, token rows, and protocol values into one accessibility-tree line; parser logic must handle that.
- Jupiter can show human-verification, marketing/login text, or an empty DOM in some browser profiles.
- A native Solana RPC balance is not equivalent to Jupiter Portfolio coverage.
- Do not publish live wallet addresses, state files, or debug dumps.
- Do not let a stale or disputed source row enter a clean total; mark it degraded/audit-only until reconciled.

## Verification

- Run the script in dry-run mode against example or explicitly provided addresses.
- Confirm no raw wallet addresses/balances are written to state.
- Confirm the report includes source-specific sections for EVM/DeBank and Solana/Jupiter when both are configured.
- Confirm row accounting reconciles and stale/disputed rows are labeled degraded or audit-only.
- Run `python3 scripts/validate-public-export.py` before publishing.
- Run a static security scan before publishing.
