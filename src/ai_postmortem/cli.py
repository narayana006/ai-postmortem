"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from . import __version__
from .draft import BUILTIN_TEMPLATES, TemplateError, build_sections, load_template, render, render_timeline
from .ingest import Event, InputError, load_alerts, load_deploys, load_pagerduty, load_slack
from .polish import CommandGenerator, polish_sections
from .timeline import anonymise, build_timeline, find_milestones

_LOADERS = (("slack", "Chat export", load_slack), ("pagerduty", "PagerDuty log", load_pagerduty),
            ("alerts", "Alert log", load_alerts), ("deploys", "Deploy events", load_deploys))


def _add_inputs(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("inputs (give at least one)")
    group.add_argument("--slack", metavar="PATH",
                       help="Slack export: a JSON file of messages, an export directory or a .zip")
    group.add_argument("--pagerduty", metavar="FILE",
                       help="PagerDuty incident log entries saved as JSON")
    group.add_argument("--alerts", metavar="FILE",
                       help="generic alert log (CSV, JSON or JSONL with time, name, state)")
    group.add_argument("--deploys", metavar="FILE",
                       help="deploy events (CSV, JSON or JSONL with time, service, version, action)")
    parser.add_argument("--people", choices=("roles", "names"), default="roles",
                        help="roles (default) replaces names with 'Responder N'; names keeps them")
    parser.add_argument("--full-timeline", action="store_true",
                        help="include chat messages that matched no rule")
    parser.add_argument("-o", "--output", metavar="FILE", help="write to FILE instead of stdout")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-postmortem",
        description="Build an incident timeline and a blameless postmortem draft from a chat "
                    "export, alert log and deploy events.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    draft = commands.add_parser("draft", help="write a postmortem draft in Markdown")
    _add_inputs(draft)
    draft.add_argument("--template", default="google-sre", metavar="NAME_OR_FILE",
                       help=f"{' or '.join(BUILTIN_TEMPLATES)} (default: google-sre), or a path "
                            "to your own template")
    draft.add_argument("--title", help="incident title (default: the first alert's summary)")
    draft.add_argument("--deploy-window", type=int, default=60, metavar="MINUTES",
                       help="how far before detection to look for a triggering deploy (default: 60)")
    draft.add_argument("--polish-command", metavar="COMMAND",
                       help="optional: reword prose sections by piping a prompt to COMMAND "
                            "(reads stdin, writes stdout). Off by default.")

    timeline = commands.add_parser("timeline", help="print only the merged timeline")
    _add_inputs(timeline)
    timeline.add_argument("--json", action="store_true", help="output JSON instead of a Markdown table")
    return parser


def _load(args: argparse.Namespace) -> tuple[list[Event], list[str]]:
    events: list[Event] = []
    sources = []
    for attribute, label, loader in _LOADERS:
        path = getattr(args, attribute)
        if path:
            loaded = loader(path)
            events.extend(loaded)
            sources.append(f"{label}: `{Path(path).name}` ({len(loaded)} events)")
    return events, sources


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not any(getattr(args, attribute) for attribute, _, _ in _LOADERS):
        parser.error("give at least one of --slack, --pagerduty, --alerts, --deploys")
    try:
        events, sources = _load(args)
        timeline = build_timeline(events)
        if not timeline:
            print("ai-postmortem: the inputs contain no events", file=sys.stderr)
            return 1
        if args.people == "roles":
            timeline = anonymise(timeline)

        if args.command == "timeline":
            if args.json:
                output = json.dumps([{"time": e.time.isoformat(), "source": e.source, "kind": e.kind,
                                      "actor": e.actor, "text": e.text} for e in timeline
                                     if args.full_timeline or e.kind != "note"], indent=2) + "\n"
            else:
                output = render_timeline(timeline, args.full_timeline) + "\n"
        else:
            template = load_template(args.template)
            milestones = find_milestones(timeline, timedelta(minutes=args.deploy_window))
            sections = build_sections(timeline, milestones, args.title, args.full_timeline, sources)
            if args.polish_command:
                sections, warnings = polish_sections(sections, CommandGenerator(args.polish_command))
                for warning in warnings:
                    print(f"ai-postmortem: warning: {warning}", file=sys.stderr)
            output = render(template, sections)
    except (InputError, TemplateError) as exc:
        print(f"ai-postmortem: error: {exc}", file=sys.stderr)
        return 2

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
