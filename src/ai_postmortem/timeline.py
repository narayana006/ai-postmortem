"""Merge events into one timeline, classify chat messages and find milestones."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Iterable

from .ingest import (ALERT_ACKNOWLEDGED, ALERT_RESOLVED, ALERT_TRIGGERED, DEPLOY, NOTE,
                     ROLLBACK, Event)

IMPACT = "impact"
CAUSE = "cause"
FACTOR = "factor"
MITIGATION = "mitigation"
RESOLUTION = "resolution"
ACTION_ITEM = "action_item"
DETECTION = "detection"

ACTION_PREFIX = re.compile(r"^\s*(?:ai|action item|action|todo|follow[- ]?up)\s*[:\-]\s*", re.I)

# Checked in order; the first rule that matches decides the kind.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    (ACTION_ITEM, re.compile(
        r"^\s*(?:ai|action item|action|todo|follow[- ]?up)\s*[:\-]|\b(?:we should|we need to|we ought to)\b",
        re.I)),
    (RESOLUTION, re.compile(
        r"\b(?:resolved|all clear|incident (?:is )?(?:over|closed)|closing (?:the |this )?incident"
        r"|fully recovered|back to normal)\b", re.I)),
    (FACTOR, re.compile(
        r"\b(?:no (?:alert|alerting|runbook|canary|dashboard|monitoring)"
        r"|(?:alert|runbook|dashboard|canary|monitoring|docs?) (?:was |is |were )?"
        r"(?:missing|out of date|outdated|stale|wrong|skipped|too slow)"
        r"|(?:wasn't|was not|never|not) (?:load[- ])?tested|took (?:us )?(?:too|so) long"
        r"|hard to (?:find|tell|see)|didn't (?:know|have access|catch))\b", re.I)),
    (CAUSE, re.compile(
        r"\b(?:root cause|caused by|because of|the (?:problem|issue|bug) (?:is|was)|culprit"
        r"|turns out|introduced (?:by|in)|is what broke|exhaust(?:ed|ing|ion))\b", re.I)),
    (MITIGATION, re.compile(
        r"\b(?:roll(?:ed|ing)? ?back|revert(?:ed|ing)?|restart(?:ed|ing)?|fail(?:ed|ing)? over"
        r"|failover|scal(?:ed|ing) (?:up|out)|disabl(?:ed|ing)|hotfix|mitigat(?:ed|ing|ion)"
        r"|drain(?:ed|ing)|block(?:ed|ing))\b", re.I)),
    (IMPACT, re.compile(
        r"^\s*impact\s*:|\b(?:customers?|users?|requests?|orders?|checkouts?|logins?|payments?)\b"
        r".*(?:\d+(?:\.\d+)?\s?%|\b(?:unable|cannot|can't|failing|failed|errors?|timeouts?"
        r"|timing out|degraded|down|affected|slow)\b)", re.I)),
    (DETECTION, re.compile(
        r"\b(?:paged|page(?:d)? for|alert (?:fired|firing)|i'm seeing|we're seeing|noticed"
        r"|reports? of|reported by)\b", re.I)),
]

_NEGATION = re.compile(
    r"\b(?:not|no|never|isn't|aren't|wasn't|hasn't|haven't|don't|didn't|won't)\b[^.;,]{0,20}$",
    re.I)


def classify(text: str) -> str:
    """Return the kind of a chat message using keyword rules."""
    for kind, pattern in _RULES:
        match = pattern.search(text)
        if not match:
            continue
        if kind in (RESOLUTION, MITIGATION):
            # "not resolved yet" and "should we roll back?" are not milestones.
            if _NEGATION.search(text[:match.start()]) or text.rstrip().endswith("?"):
                continue
        return kind
    return NOTE


def build_timeline(events: Iterable[Event]) -> list[Event]:
    """Sort events by time and classify chat messages. Input order breaks ties."""
    ordered = sorted(enumerate(events), key=lambda pair: (pair[1].time, pair[0]))
    return [event.with_kind(classify(event.text)) if event.source == "chat" else event
            for _, event in ordered]


def anonymise(events: list[Event]) -> list[Event]:
    """Replace people's names with stable role labels ("Responder 1", ...).

    Names are taken from the actors of chat and alert events; occurrences of a
    full name, its first name or an @mention inside message text are replaced
    too. Deploy actors are replaced when they match a known person.
    """
    labels: dict[str, str] = {}
    for event in events:
        if event.actor and event.source != "deploy" and event.actor not in labels:
            labels[event.actor] = f"Responder {len(labels) + 1}"
    if not labels:
        return events
    replacements: dict[str, str] = {}
    for name, label in labels.items():
        replacements.setdefault(name, label)
        first = name.split()[0]
        if len(name.split()) > 1 and len(first) >= 3:
            replacements.setdefault(first, label)
    pattern = re.compile(
        r"@?(?<![\w-])(?:" + "|".join(re.escape(name) for name in
                                       sorted(replacements, key=len, reverse=True)) + r")(?![\w-])")

    def scrub(text: str) -> str:
        return pattern.sub(lambda m: replacements[m.group(0).lstrip("@")], text)

    return [replace(event, actor=labels.get(event.actor, "" if event.source == "deploy" else event.actor),
                    text=scrub(event.text)) for event in events]


@dataclass(frozen=True)
class Milestones:
    """Key moments of the incident. Any of them may be missing."""

    trigger: Event | None = None  # change that shipped shortly before detection
    detected: Event | None = None
    acknowledged: Event | None = None
    mitigated: Event | None = None
    resolved: Event | None = None

    @property
    def started(self) -> datetime | None:
        """Best estimate of when the incident began."""
        if self.trigger:
            return self.trigger.time
        return self.detected.time if self.detected else None

    def between(self, start: str, end: str) -> timedelta | None:
        first = self.started if start == "started" else getattr(getattr(self, start), "time", None)
        second = getattr(getattr(self, end), "time", None)
        if first is None or second is None or second < first:
            return None
        return second - first


def find_milestones(timeline: list[Event], deploy_window: timedelta = timedelta(minutes=60)) -> Milestones:
    """Derive milestones from a classified timeline.

    Detection is the first triggered alert, or the first chat message when
    there are no alerts. The suspected trigger is the most recent deploy
    within `deploy_window` before detection.
    """
    if not timeline:
        return Milestones()
    alerts = [e for e in timeline if e.kind == ALERT_TRIGGERED]
    chat = [e for e in timeline if e.source == "chat"]
    detected = alerts[0] if alerts else (chat[0] if chat else None)
    if detected is None:
        return Milestones()
    after = [e for e in timeline if e.time >= detected.time and e is not detected]

    trigger = None
    for event in timeline:
        if event.kind == DEPLOY and detected.time - deploy_window <= event.time <= detected.time:
            trigger = event

    acknowledged = next((e for e in after if e.kind == ALERT_ACKNOWLEDGED), None)
    if acknowledged is None and detected.source == "alert":
        acknowledged = next((e for e in after if e.source == "chat"), None)
    mitigated = next((e for e in after if e.kind in (ROLLBACK, MITIGATION)), None)
    alert_resolutions = [e for e in after if e.kind == ALERT_RESOLVED]
    resolved = (alert_resolutions[-1] if alert_resolutions
                else next((e for e in after if e.kind == RESOLUTION), None))
    return Milestones(trigger, detected, acknowledged, mitigated, resolved)
