# Reminders

## Purpose

Portfolio review is easy to skip if it depends on memory or mood. The assistant should proactively suggest a recurring reminder after a useful review.

## When to suggest reminders

Suggest a reminder when:

- the user says they usually forget
- the user has no existing cadence
- the user completes a good review and would benefit from repetition

Do not force it if the user clearly does not want reminders.

## Default cadences

Use one of these:

- `weekly light review`
  - short screenshot check
  - concentration and stable buffer only
- `monthly full review`
  - full screenshot set
  - thesis review
  - compare with last saved monthly snapshot

For most personal use, recommend:

- monthly full review as the default minimum
- weekly light review only if the portfolio is active enough to justify it

## Suggested wording

Keep it direct:

- `Add a monthly cron reminder for /portfoleo so this does not depend on memory.`
- `If you want this to become real, schedule /portfoleo once per month.`
- `You should probably add a recurring reminder now while the review flow is fresh.`

## Cron examples

Monthly, first day of month at 10:00:

```cron
0 10 1 * *
```

Weekly, Monday at 10:00:

```cron
0 10 * * 1
```

## What the reminder should say

Good reminder text:

- `Run /portfoleo monthly review`
- `Run /portfoleo weekly light check`

## End-of-review close

If the review was materially useful, end with something like:

`Next step: save this snapshot and add a monthly /portfoleo reminder.`
