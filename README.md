# ai-postmortem

Build an incident timeline and a blameless postmortem draft from the raw record of an incident: the chat export, the alert log and the deploy events.

**Status:** first working version (v0.1.0). The command-line tool reads Slack exports, PagerDuty log entries, generic alert logs and deploy logs from files, merges them into one timeline, and fills a Google SRE, Atlassian or custom template. Everything is rule-based and runs offline. Not built yet: fetching from the Slack, PagerDuty or Opsgenie APIs (so `--pagerduty` takes a file, not an incident id) and the Slack bot.

## Why

The slow part of a postmortem is reconstruction: scrolling the incident channel, lining it up against pages and deploys, and working out when things were detected, mitigated and resolved. This tool does that part in a second and hands you a draft with the gaps clearly marked, so review time goes on the analysis.

It only drafts. It never posts or publishes anything, and every inferred statement in the draft says that it is inferred.

To score a postmortem that is already written, see [incident-review-copilot](https://github.com/narayana006/incident-review-copilot); this tool stops where that one starts.

## Install

Requires Python 3.10 or newer. No runtime dependencies.

```bash
pip install git+https://github.com/narayana006/ai-postmortem
```

## Quick start

The repository ships a small fictional incident in `examples/`: a Slack export directory, a PagerDuty log and a deploy log.

```bash
git clone https://github.com/narayana006/ai-postmortem
cd ai-postmortem
ai-postmortem draft --slack examples/slack-export \
  --pagerduty examples/pagerduty-log.json \
  --deploys examples/deploys.csv
```

The first half of the output (the full file is [examples/draft-google-sre.md](examples/draft-google-sre.md)):

```markdown
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
```

The draft continues with lessons learned, the full timeline and a table of key timings.

## What it reads

| Flag | Input | Format |
| --- | --- | --- |
| `--slack PATH` | Slack channel export | A JSON file holding a list of messages, an unpacked export directory, or the export `.zip`. `users.json` is used to resolve names when present. Joins and other housekeeping messages are skipped. |
| `--pagerduty FILE` | PagerDuty incident log | The `log_entries` JSON for one incident (trigger, acknowledge and resolve entries are recognised). |
| `--alerts FILE` | Any other alert log | CSV, JSON or JSON Lines with `time`, `name` and `state` (`firing`, `acknowledged`, `resolved`); `severity` and `service` are optional. |
| `--deploys FILE` | Deploy events | CSV, JSON or JSON Lines with `time` and `service`; `version`, `action` (`deploy` or `rollback`), `environment` and `actor` are optional. |

Give at least one. Times may be ISO 8601 or Unix epoch; timestamps without an offset are read as UTC, and all output is in UTC.

## How the draft is built

1. **Merge.** All events are sorted into one timeline.
2. **Classify.** Each chat message is matched against keyword rules and tagged as detection, impact, candidate cause, contributing factor, mitigation, resolution or action item. Negated statements ("not resolved yet") and questions ("should we roll back?") are not treated as milestones. Messages that match nothing are left out of the timeline unless you pass `--full-timeline`.
3. **Find milestones.** Detection is the first triggered alert (or the first chat message if there are no alerts). The suspected trigger is the latest deploy in the 60 minutes before detection (`--deploy-window`). Mitigation is the first rollback or mitigation message; resolution is the last alert resolution, or the first "resolved" message when there are no alerts.
4. **Write sections.** Impact, causes and contributing factors are quoted from the channel with their timestamps; timings are computed from the milestones. Where the inputs say nothing, the section says `_Needs input:_` and what is missing rather than guessing.
5. **Keep it blameless.** By default people are replaced by stable labels (`Responder 1`, `Responder 2`, ...) in the "Who" column and inside message text. Pass `--people names` to keep names.

## Other commands and options

Print only the merged timeline (here with the generic alert log instead of the PagerDuty one):

```bash
ai-postmortem timeline --slack examples/slack-export --alerts examples/alerts.csv --deploys examples/deploys.csv
```

```markdown
| Time (UTC) | Source | Who | Event |
| --- | --- | --- | --- |
| 11:20 | deploy | - | **Deploy:** Deploy of search-api v1.9.2 (production) |
| 13:58 | deploy | - | **Deploy:** Deploy of checkout-api v2.41.0 (production) |
| 14:02 | alert | - | **Alert triggered:** CheckoutApi5xxRateHigh [critical] |
| 14:03 | chat | Responder 1 | **Detection:** Paged for checkout-api 5xx. Looking now. |
| 14:04 | alert | - | **Alert triggered:** OrdersDbClientTimeouts [warning] |
| 14:05 | chat | Responder 2 | **Detection:** I'm seeing it too, the error rate dashboard shows 5xx climbing since about 14:00 |
| 14:07 | chat | Responder 3 | **Impact:** about 18% of checkout requests are failing with 503, support has 12 tickets so far |
| 14:24 | chat | Responder 1 | **Cause (candidate):** Turns out the pool size was cut from 50 to 5 per pod in v2.41.0, connections are exhausted under normal load |
| 14:26 | chat | Responder 3 | **Contributing factor:** It took so long to spot because there is no alert on pool saturation and the dashboard is hard to find |
| 14:29 | chat | Responder 1 | **Mitigation:** Rolling back checkout-api to v2.40.3 now |
| 14:31 | deploy | Responder 1 | **Rollback:** Rollback of checkout-api to v2.40.3 (production) |
| 14:41 | alert | - | **Alert resolved:** OrdersDbClientTimeouts [warning] |
| 14:44 | alert | - | **Alert resolved:** CheckoutApi5xxRateHigh [critical] |
| 14:45 | chat | Responder 1 | **Resolved:** Error rate back to normal for 10 minutes. Incident resolved, thanks Responder 2 and Responder 3 |
| 14:48 | chat | Responder 3 | **Action item:** AI: add an alert on database connection pool saturation for checkout-api |
| 14:49 | chat | Responder 2 | **Action item:** Follow-up: the pool size change was not load tested, add a load test stage for connection settings |
| 14:51 | chat | Responder 1 | **Action item:** We should link the pool dashboard from the checkout-api runbook |
```

Add `--json` for machine-readable output.

Templates: `--template google-sre` (default), `--template atlassian`, or a path to your own file. A template is plain Markdown with `$field` placeholders; see [examples/custom-template.md](examples/custom-template.md):

```bash
ai-postmortem draft --slack examples/slack-export --deploys examples/deploys.csv \
  --template examples/custom-template.md -o postmortem.md
```

Available fields: `$title`, `$date`, `$summary`, `$impact`, `$trigger`, `$root_cause`, `$detection`, `$response`, `$resolution`, `$contributing_factors`, `$action_items`, `$timeline`, `$metrics`, `$sources`. An unknown field is an error; write `$$` for a literal dollar sign.

Other flags for `draft`: `--title "..."` sets the incident title (default: the first alert's summary), `-o FILE` writes to a file.

### Optional rewording with a text generator

Off by default. `--polish-command COMMAND` pipes a prompt for each prose section (summary, impact, root cause, contributing factors) to a command of your choice on stdin and uses what it prints on stdout. The command can be anything: a script that calls a local model, or a wrapper around any OpenAI-compatible HTTP endpoint. Tables and the timeline are never sent, and if the command fails or prints nothing the deterministic text is kept. Remember that the prompt contains incident text; only point it at something you are allowed to send that to.

From Python, pass any object with a `generate(prompt) -> str` method to `ai_postmortem.polish.polish_sections`.

## Features

- [x] Ingest Slack channel exports (file, directory or zip)
- [x] Ingest PagerDuty log entries, generic alert logs and deploy logs from files
- [x] Reconstruct a timestamped, classified timeline with detection, mitigation and resolution timings
- [x] Draft impact, trigger, candidate root causes, contributing factors and action items
- [x] Blameless by default: names replaced by role labels
- [x] Pluggable templates (Google SRE, Atlassian, custom file)
- [x] CLI (`draft`, `timeline`)
- [ ] Fetch directly from the Slack and PagerDuty APIs
- [ ] Opsgenie timelines
- [ ] Slack bot

## Limitations

- Classification is keyword rules written for English-language incident chat. It will miss statements phrased unusually and will occasionally mislabel one; read the timeline before trusting the sections built from it.
- "Root causes" are quotes of what people said during the incident plus a deploy chosen by timing. Neither is verified analysis.
- Impact numbers are whatever was typed in the channel. Check them against your metrics.
- One incident per run. A Slack export directory containing several channels is read as a single conversation.
- Thread structure is ignored; replies are placed by their own timestamps.
- Name replacement covers people who posted in the chat or appear as the actor in the alert log. A person who is only mentioned by first name and never posted is not replaced. Deploy actors that are not known people are dropped in the default mode.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Contributing

Issues and pull requests are welcome. The most useful reports are chat messages that were classified wrongly (with the names removed) and export formats that fail to load. Please add a test with any change to the rules in `src/ai_postmortem/timeline.py`.

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
