# Postmortem: checkout-api 5xx error rate above 5% for 2 minutes

- **Date:** 2026-03-14
- **Status:** Draft generated from raw inputs. Review every section before sharing.
- **Authors:** _add the people who reviewed this draft_

## Summary

On 2026-03-14, from about 13:58 to 14:44 UTC (46m), an incident occurred: checkout-api 5xx error rate above 5% for 2 minutes. It was first detected at 14:02 UTC by an alert. Deploy of checkout-api v2.41.0 (production) at 13:58 UTC shipped 4m before detection and is the suspected trigger. Mitigation started at 14:29 UTC: Rolling back checkout-api to v2.40.3 now.

## Impact

Impact statements from the incident channel (confirm the numbers against metrics before publishing):

- 14:07 UTC: "Impact: about 18% of checkout requests are failing with 503, support has 12 tickets so far"

Duration of impact (estimated from the timeline): 46m.

## Root causes

Candidate causes stated during the incident (not yet verified):

- 14:24 UTC: "Turns out the pool size was cut from 50 to 5 per pod in v2.41.0, connections are exhausted under normal load"

Suspected trigger: Deploy of checkout-api v2.41.0 (production) at 13:58 UTC.

## Trigger

Deploy of checkout-api v2.41.0 (production) at 13:58 UTC, 4m before the first sign of trouble. This is inferred from timing only; confirm it.

## Detection

- Detected at 14:02 UTC by alert: "checkout-api 5xx error rate above 5% for 2 minutes"
- Time to detect: 4m after the suspected trigger.
- Acknowledged at 14:02 UTC (47s after detection).

## Resolution

- 14:29 UTC: Rolling back checkout-api to v2.40.3 now
- 14:31 UTC: Rollback of checkout-api to v2.40.3 (production)

- First mitigation at 14:29 UTC (27m after detection).
- Resolved at 14:44 UTC: "Resolved automatically: error rate back under threshold"
- Time to resolve: 42m after detection.

## Action items

| # | Action | Owner | Due |
| --- | --- | --- | --- |
| 1 | add an alert on database connection pool saturation for checkout-api | TBD | TBD |
| 2 | the pool size change was not load tested, add a load test stage for connection settings | TBD | TBD |
| 3 | We should link the pool dashboard from the checkout-api runbook | TBD | TBD |

## Lessons learned

### What went well

_Needs input:_ fill in during the review meeting.

### What went wrong

- 14:26 UTC: "It took so long to spot because there is no alert on pool saturation and the dashboard is hard to find"

### Where we got lucky

_Needs input:_ fill in during the review meeting.

## Timeline

All times are UTC.

| Time (UTC) | Source | Who | Event |
| --- | --- | --- | --- |
| 11:20 | deploy | - | **Deploy:** Deploy of search-api v1.9.2 (production) |
| 13:58 | deploy | - | **Deploy:** Deploy of checkout-api v2.41.0 (production) |
| 14:02 | alert | - | **Alert triggered:** checkout-api 5xx error rate above 5% for 2 minutes |
| 14:02 | alert | - | **Alert:** Notified on-call by push notification |
| 14:02 | alert | Responder 1 | **Alert acknowledged:** Acknowledged by Responder 1 |
| 14:03 | chat | Responder 1 | **Detection:** Paged for checkout-api 5xx. Looking now. |
| 14:05 | chat | Responder 2 | **Detection:** I'm seeing it too, the error rate dashboard shows 5xx climbing since about 14:00 |
| 14:07 | chat | Responder 3 | **Impact:** about 18% of checkout requests are failing with 503, support has 12 tickets so far |
| 14:24 | chat | Responder 1 | **Cause (candidate):** Turns out the pool size was cut from 50 to 5 per pod in v2.41.0, connections are exhausted under normal load |
| 14:26 | chat | Responder 3 | **Contributing factor:** It took so long to spot because there is no alert on pool saturation and the dashboard is hard to find |
| 14:29 | chat | Responder 1 | **Mitigation:** Rolling back checkout-api to v2.40.3 now |
| 14:31 | deploy | Responder 1 | **Rollback:** Rollback of checkout-api to v2.40.3 (production) |
| 14:44 | alert | - | **Alert resolved:** Resolved automatically: error rate back under threshold |
| 14:45 | chat | Responder 1 | **Resolved:** Error rate back to normal for 10 minutes. Incident resolved, thanks Responder 2 and Responder 3 |
| 14:48 | chat | Responder 3 | **Action item:** AI: add an alert on database connection pool saturation for checkout-api |
| 14:49 | chat | Responder 2 | **Action item:** Follow-up: the pool size change was not load tested, add a load test stage for connection settings |
| 14:51 | chat | Responder 1 | **Action item:** We should link the pool dashboard from the checkout-api runbook |

## Supporting information

| Metric | Value |
| --- | --- |
| Suspected trigger | 13:58 UTC |
| Detected | 14:02 UTC |
| Acknowledged | 14:02 UTC |
| First mitigation | 14:29 UTC |
| Resolved | 14:44 UTC |
| Time to detect | 4m |
| Time to acknowledge | 47s |
| Time to mitigate | 27m |
| Time to resolve | 42m |

- Chat export: `slack-export` (14 events)
- PagerDuty log: `pagerduty-log.json` (4 events)
- Deploy events: `deploys.csv` (3 events)
- Events read: 14 chat messages, 4 alert log entries, 3 deploy events.
