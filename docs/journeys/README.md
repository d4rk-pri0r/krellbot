# Public journey specifications

### Rules for every journey
- No step asks for an account, a payment or an exchange key.
- No step sends a live order. Live trading stays disabled throughout.
- Every error says what went wrong in plain words. Nothing fails silently, and old data never appears as current.
- The same inputs always produce the same results.

## Scenario IDs

Scenario IDs use J<journey>.<scenario>. The approved set is J1.1 through J7.5: seven journeys with five scenarios each. Each journey test title starts with its exact scenario ID.

## Time limits

| Moment | Limit |
| --- | --- |
| A new job appears in Jobs | 5 seconds after submit |
| Jobs shows a job's final state | 15 seconds after the job ends |
| A Retry recovers after the workstation is back | 10 seconds |
| 100,000-bar scroll and bar inspection | The thresholds already in `ns20-100k-rows.spec.ts` |

## Journey files

- j1-author.md
- j2-validate.md
- j3-research-jobs.md
- j4-inspect.md
- j5-paper.md
- j6-pause-restart.md
- j7-export.md
