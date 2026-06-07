# History Format

## Purpose

After each screenshot-based review, save a compact canonical record. Next month, compare against that record instead of relying on memory.

## Where to store

Store one markdown file per review outside the skill, for example:

- `portfolio-history/2026-03.md`
- `portfolio-history/2026-04.md`

## Minimal record

Use this structure:

```markdown
# 2026-03 Portfolio Snapshot

## Source
- screenshots from DeBank / wallet UI
- date reviewed: 2026-03-02

## Visible allocation
- BTC:
- ETH:
- Stables:
- Thesis positions:
- Venture positions:
- Unclassified:

## Largest positions
- symbol - approximate weight - notes

## New positions since previous review
- ...

## Closed positions since previous review
- ...

## Likely issues
- ...

## Candidate actions
- ...

## Missing visibility
- ...
```

## Comparison rule

At the next review:

1. open the previous monthly file
2. compare visible allocation
3. compare largest positions
4. compare new and closed names
5. check whether previous candidate actions were executed

## Why this is enough

For personal monthly reviews, the main value is:

- direction of change
- concentration drift
- stable buffer drift
- thesis discipline

That does not require paid APIs if the screenshot record is kept consistently.
