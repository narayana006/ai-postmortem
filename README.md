# ai-postmortem

> Generate blameless postmortem drafts from incident Slack channels, PagerDuty/Opsgenie timelines and deploy logs.

**Status:** 🚧 Early stage — design and roadmap published, implementation in progress. Stars, issues and ideas welcome.

## Why

Writing postmortems is slow, so they get delayed or skipped and the lessons are lost.

## Planned features

- [ ] Ingest Slack channel exports, PagerDuty / Opsgenie timelines, deploy logs
- [ ] Reconstructs a timestamped timeline
- [ ] Drafts impact, root cause, contributing factors and action items
- [ ] Pluggable templates (Google SRE, Atlassian, custom)
- [ ] Slack bot and CLI

## Intended usage

```
ai-postmortem draft --slack export.zip --pagerduty INC123 --template google-sre
```

_The interface above is the target design and may change._

## Roadmap

1. Core implementation of the first feature set
2. Examples and tests
3. CI and first tagged release
4. Docs and integrations

## Related

- [ai-incident-management-companion](https://github.com/narayana006/ai-incident-management-companion)

## Contributing

Contributions are welcome. Open an issue to discuss an idea or pick an unchecked item from the feature list.

## License

[MIT](LICENSE)
