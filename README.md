# ai-postmortem

Generate blameless postmortem drafts from incident Slack channels, PagerDuty/Opsgenie timelines and deploy logs.

> **Project status: planning. There is no working code in this repository yet.**
> This README describes what the project will do. Nothing below can be installed or run today.
> Features are ticked off in the checklist as they are built.

## What it is

A command-line tool and Slack bot.

**The problem it solves:** Writing postmortems is slow, so they get delayed or skipped and the lessons are lost.

## Who it is for

On-call engineers and incident commanders who have to write the postmortem after an incident.

## How it will work

1. You give the tool the incident's Slack export, paging timeline and deploy log.
2. It rebuilds a timestamped timeline and drafts impact, root cause, contributing factors and action items in a blameless style.
3. You review and edit the draft; the tool never publishes anything by itself.

## Planned features

Unticked items are not built yet.

- [ ] Ingest Slack channel exports, PagerDuty / Opsgenie timelines, deploy logs
- [ ] Reconstructs a timestamped timeline
- [ ] Drafts impact, root cause, contributing factors and action items
- [ ] Pluggable templates (Google SRE, Atlassian, custom)
- [ ] Slack bot and CLI

## Planned usage

This is the intended interface, shown so you can judge the design. **It does not work yet**, and names may change before the first release.

```bash
ai-postmortem draft --slack export.zip --pagerduty INC123 --template google-sre
```

## Related

- [ai-incident-management-companion](https://github.com/narayana006/ai-incident-management-companion)

## Contributing

Feedback on the design is the most useful contribution right now. Open an issue to suggest a feature, question an approach or describe your use case. Code contributions are welcome once the first version lands.

## Author

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
