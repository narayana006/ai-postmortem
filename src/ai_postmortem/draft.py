"""Turn a classified timeline into the sections of a postmortem draft."""

from __future__ import annotations

from datetime import timedelta
from importlib import resources
from pathlib import Path
from string import Template

from .ingest import (ALERT_ACKNOWLEDGED, ALERT_OTHER, ALERT_RESOLVED, ALERT_TRIGGERED, DEPLOY,
                     NOTE, ROLLBACK, Event)
from .timeline import (ACTION_ITEM, ACTION_PREFIX, CAUSE, DETECTION, FACTOR, IMPACT, MITIGATION,
                       RESOLUTION, Milestones)

BUILTIN_TEMPLATES = ("google-sre", "atlassian")

_LABELS = {
    ALERT_TRIGGERED: "Alert triggered", ALERT_ACKNOWLEDGED: "Alert acknowledged",
    ALERT_RESOLVED: "Alert resolved", ALERT_OTHER: "Alert", DEPLOY: "Deploy",
    ROLLBACK: "Rollback", IMPACT: "Impact", CAUSE: "Cause (candidate)",
    FACTOR: "Contributing factor", MITIGATION: "Mitigation", RESOLUTION: "Resolved",
    ACTION_ITEM: "Action item", DETECTION: "Detection", NOTE: "",
}

NEEDS_INPUT = "_Needs input:_"


class TemplateError(ValueError):
    pass


def format_duration(delta: timedelta | None) -> str:
    if delta is None:
        return "unknown"
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return f"{int(delta.total_seconds())}s"
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{days}d" if days else "", f"{hours}h" if hours else "", f"{minutes}m" if minutes else ""]
    return " ".join(part for part in parts if part)


def _shorten(text: str, limit: int = 220) -> str:
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


class _Clock:
    """Formats times as HH:MM UTC, adding the date once the day changes."""

    def __init__(self, timeline: list[Event]):
        self.first_day = timeline[0].time.date() if timeline else None

    def __call__(self, event_or_time) -> str:
        when = event_or_time.time if isinstance(event_or_time, Event) else event_or_time
        if when.date() == self.first_day:
            return when.strftime("%H:%M")
        return when.strftime("%Y-%m-%d %H:%M")


def render_timeline(timeline: list[Event], full: bool = False) -> str:
    """Markdown table of the timeline. Unclassified chat is left out unless `full`."""
    clock = _Clock(timeline)
    rows = ["| Time (UTC) | Source | Who | Event |", "| --- | --- | --- | --- |"]
    for event in timeline:
        if event.kind == NOTE and not full:
            continue
        label = _LABELS.get(event.kind, "")
        text = _shorten(event.text)
        if label and text.lower().startswith(label.lower() + ":"):
            text = f"**{label}:**{text[len(label) + 1:]}"
        elif label:
            text = f"**{label}:** {text}"
        rows.append(f"| {clock(event)} | {event.source} | {_cell(event.actor) or '-'} | {_cell(text)} |")
    return "\n".join(rows)


def _quotes(events: list[Event], clock: _Clock) -> list[str]:
    seen, lines = set(), []
    for event in events:
        key = event.text.lower()
        if key not in seen:
            seen.add(key)
            lines.append(f'- {clock(event)} UTC: "{_shorten(event.text)}"')
    return lines


def build_sections(timeline: list[Event], milestones: Milestones, title: str | None = None,
                   full_timeline: bool = False, sources: list[str] | None = None) -> dict[str, str]:
    """Return every template field as Markdown text."""
    clock = _Clock(timeline)
    m = milestones
    by_kind: dict[str, list[Event]] = {}
    for event in timeline:
        by_kind.setdefault(event.kind, []).append(event)

    named = f": {title}" if title else ""
    if not title and m.detected and m.detected.source == "alert":
        title = m.detected.text
        named = f": {title}"
    elif not title:
        title = f"Incident on {timeline[0].time:%Y-%m-%d}" if timeline else "Incident"

    # Summary ---------------------------------------------------------------
    summary = []
    if m.started and m.resolved:
        summary.append(
            f"On {m.started:%Y-%m-%d}, from about {clock(m.started)} to {clock(m.resolved)} UTC "
            f"({format_duration(m.between('started', 'resolved'))}), an incident occurred{named}.")
    elif m.started:
        summary.append(f"On {m.started:%Y-%m-%d} at about {clock(m.started)} UTC an incident began{named}. "
                       f"The inputs do not show when it was resolved.")
    if m.detected:
        how = "an alert" if m.detected.source == "alert" else "a message in the incident channel"
        summary.append(f"It was first detected at {clock(m.detected)} UTC by {how}.")
    if m.trigger:
        summary.append(
            f"{m.trigger.text} at {clock(m.trigger)} UTC shipped "
            f"{format_duration(m.between('trigger', 'detected'))} before detection and is the "
            "suspected trigger.")
    if m.mitigated:
        step = _shorten(m.mitigated.text, 120)
        summary.append(f"Mitigation started at {clock(m.mitigated)} UTC: {step}"
                       + ("" if step.endswith((".", "!", "?")) else "."))
    if not summary:
        summary.append(f"{NEEDS_INPUT} the inputs contained no events.")

    # Impact ----------------------------------------------------------------
    impact = _quotes(by_kind.get(IMPACT, []), clock)
    if impact:
        impact.insert(0, "Impact statements from the incident channel (confirm the numbers "
                         "against metrics before publishing):\n")
    else:
        impact.append(f"{NEEDS_INPUT} no impact statements were found. State who was affected, "
                      "how, and for how long.")
    if m.started and m.resolved:
        impact.append(f"\nDuration of impact (estimated from the timeline): "
                      f"{format_duration(m.between('started', 'resolved'))}.")

    # Trigger and root cause --------------------------------------------------
    if m.trigger:
        trigger = (f"{m.trigger.text} at {clock(m.trigger)} UTC, "
                   f"{format_duration(m.between('trigger', 'detected'))} before the first sign of "
                   "trouble. This is inferred from timing only; confirm it.")
    else:
        trigger = f"{NEEDS_INPUT} no deploy was found in the hour before detection."
    causes = _quotes(by_kind.get(CAUSE, []), clock)
    if causes:
        root_cause = ("Candidate causes stated during the incident (not yet verified):\n\n"
                      + "\n".join(causes))
    else:
        root_cause = f"{NEEDS_INPUT} nobody stated a cause in the incident channel."
    if m.trigger:
        root_cause += f"\n\nSuspected trigger: {m.trigger.text} at {clock(m.trigger)} UTC."

    # Detection -------------------------------------------------------------
    if m.detected:
        source = "alert" if m.detected.source == "alert" else "chat message"
        detection = [f"- Detected at {clock(m.detected)} UTC by {source}: \"{_shorten(m.detected.text)}\""]
        if m.trigger:
            detection.append(f"- Time to detect: {format_duration(m.between('trigger', 'detected'))} "
                             "after the suspected trigger.")
        if m.acknowledged:
            detection.append(f"- Acknowledged at {clock(m.acknowledged)} UTC "
                             f"({format_duration(m.between('detected', 'acknowledged'))} after detection).")
    else:
        detection = [f"{NEEDS_INPUT} no alert or chat message marks the detection."]

    # Response and resolution -------------------------------------------------
    steps = [e for e in timeline if e.kind in (MITIGATION, ROLLBACK)]
    response = [f"- {clock(e)} UTC: {_shorten(e.text)}" for e in steps] or [
        f"{NEEDS_INPUT} no mitigation steps were recognised in the inputs."]
    if m.resolved:
        resolution = [f"- Resolved at {clock(m.resolved)} UTC: \"{_shorten(m.resolved.text)}\"",
                      f"- Time to resolve: {format_duration(m.between('detected', 'resolved'))} "
                      "after detection."]
        if m.mitigated:
            resolution.insert(0, f"- First mitigation at {clock(m.mitigated)} UTC "
                                 f"({format_duration(m.between('detected', 'mitigated'))} after detection).")
    else:
        resolution = [f"{NEEDS_INPUT} the inputs do not show a resolution."]

    # Contributing factors ----------------------------------------------------
    factors = _quotes(by_kind.get(FACTOR, []), clock)
    if m.detected and m.detected.source == "chat":
        factors.append("- The incident was first raised by a person in chat; no alert fired before that.")
    ack = m.between("detected", "acknowledged")
    if ack and ack > timedelta(minutes=5):
        factors.append(f"- Acknowledgement took {format_duration(ack)} after the first alert.")
    lag = m.between("trigger", "detected") if m.trigger else None
    if lag and lag > timedelta(minutes=10):
        factors.append(f"- Detection came {format_duration(lag)} after the suspected trigger.")
    if not factors:
        factors.append(f"{NEEDS_INPUT} none were identified automatically.")

    # Action items ----------------------------------------------------------
    actions = []
    for event in by_kind.get(ACTION_ITEM, []):
        text = ACTION_PREFIX.sub("", event.text).strip()
        if text and text.lower() not in (a.lower() for a in actions):
            actions.append(text)
    if actions:
        rows = ["| # | Action | Owner | Due |", "| --- | --- | --- | --- |"]
        rows += [f"| {i} | {_cell(_shorten(a))} | TBD | TBD |" for i, a in enumerate(actions, 1)]
        action_items = "\n".join(rows)
    else:
        action_items = f"{NEEDS_INPUT} no action items were proposed in the incident channel."

    # Metrics ---------------------------------------------------------------
    def at(event: Event | None) -> str:
        return f"{clock(event)} UTC" if event else "unknown"

    metrics = "\n".join([
        "| Metric | Value |", "| --- | --- |",
        f"| Suspected trigger | {at(m.trigger)} |",
        f"| Detected | {at(m.detected)} |",
        f"| Acknowledged | {at(m.acknowledged)} |",
        f"| First mitigation | {at(m.mitigated)} |",
        f"| Resolved | {at(m.resolved)} |",
        f"| Time to detect | {format_duration(m.between('trigger', 'detected')) if m.trigger else 'unknown'} |",
        f"| Time to acknowledge | {format_duration(m.between('detected', 'acknowledged'))} |",
        f"| Time to mitigate | {format_duration(m.between('detected', 'mitigated'))} |",
        f"| Time to resolve | {format_duration(m.between('detected', 'resolved'))} |",
    ])

    counts = {source: sum(1 for e in timeline if e.source == source)
              for source in ("chat", "alert", "deploy")}
    source_lines = [f"- {line}" for line in (sources or [])]
    source_lines.append(f"- Events read: {counts['chat']} chat messages, {counts['alert']} alert "
                        f"log entries, {counts['deploy']} deploy events.")

    return {
        "title": title,
        "date": f"{timeline[0].time:%Y-%m-%d}" if timeline else "unknown",
        "summary": " ".join(summary),
        "impact": "\n".join(impact),
        "trigger": trigger,
        "root_cause": root_cause,
        "detection": "\n".join(detection),
        "response": "\n".join(response),
        "resolution": "\n".join(resolution),
        "contributing_factors": "\n".join(factors),
        "action_items": action_items,
        "timeline": render_timeline(timeline, full_timeline),
        "metrics": metrics,
        "sources": "\n".join(source_lines),
    }


def load_template(name_or_path: str) -> str:
    """Return a built-in template by name, or read a custom template file."""
    if name_or_path in BUILTIN_TEMPLATES:
        return resources.files("ai_postmortem").joinpath(
            "templates", f"{name_or_path}.md").read_text("utf-8")
    path = Path(name_or_path)
    if not path.is_file():
        raise TemplateError(f"unknown template {name_or_path!r}: not one of "
                            f"{', '.join(BUILTIN_TEMPLATES)} and not a file")
    return path.read_text("utf-8")


def render(template_text: str, sections: dict[str, str]) -> str:
    """Fill `$field` placeholders. Unknown placeholders are an error."""
    try:
        return Template(template_text).substitute(sections).rstrip() + "\n"
    except KeyError as exc:
        raise TemplateError(f"template uses unknown field ${exc.args[0]}; available fields: "
                            + ", ".join(f"${name}" for name in sections)) from None
    except ValueError as exc:
        raise TemplateError(f"invalid template: {exc} (write $$ for a literal dollar sign)") from None
