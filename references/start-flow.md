# Start Flow

## Purpose

When the user types `/portfoleo`, the assistant should not wait for a perfectly structured request. Start with a short operational prompt that collects only the minimum needed to proceed.

## Default first reply

Use this structure:

```text
/portfoleo started.

Send:
1. 3-4 screenshots:
- total portfolio overview
- token list sorted by value
- protocol/staking positions if they matter
- recent activity if visible

2. Short text:
- target structure, if you have one
- what changed since the last review
- whether there is a previous monthly snapshot file

After that I will give:
- visible facts
- likely issues
- candidate actions
- what is missing

At the end I will also suggest a reminder cadence, usually monthly.
```

## Shortened variant

If the user already sent screenshots, use:

```text
/portfoleo started.

Add 3 short items:
- target structure
- what changed since the last review
- whether there is a previous monthly snapshot file

Then I will do the review and suggest a reminder cadence.
```

## Style rules

- Keep the first reply short and operational.
- Do not front-load analysis before the inputs arrive.
- Mention the reminder cadence up front so the habit-forming part is expected, not optional.
