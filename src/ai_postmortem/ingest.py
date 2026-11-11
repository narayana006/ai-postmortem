"""Read raw incident inputs (chat export, alert log, deploy events) into events."""

from __future__ import annotations

import csv
import html
import io
import json
import re
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Event kinds. Alert and deploy kinds are set here; chat messages start as
# NOTE and are classified later in timeline.py.
ALERT_TRIGGERED = "alert_triggered"
ALERT_ACKNOWLEDGED = "alert_acknowledged"
ALERT_RESOLVED = "alert_resolved"
ALERT_OTHER = "alert_other"
DEPLOY = "deploy"
ROLLBACK = "rollback"
NOTE = "note"


class InputError(ValueError):
    """An input file is missing, unreadable or not in a supported shape."""


@dataclass(frozen=True)
class Event:
    time: datetime
    source: str  # "chat", "alert" or "deploy"
    actor: str  # person or system that produced the event ("" if unknown)
    text: str
    kind: str = NOTE
    service: str = ""

    def with_kind(self, kind: str) -> "Event":
        return replace(self, kind=kind)


def parse_time(value: object) -> datetime:
    """Parse an ISO 8601 string or a Unix epoch value into an aware UTC datetime.

    Timestamps without an offset are taken to be UTC.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if re.fullmatch(r"\d{9,11}(\.\d+)?", text):
        return datetime.fromtimestamp(float(text), tz=timezone.utc)
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise InputError(f"unrecognised timestamp: {value!r}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Chat (Slack export)
# --------------------------------------------------------------------------

# Slack marks joins, topic changes and similar housekeeping with a subtype.
_KEPT_SUBTYPES = {None, "", "bot_message", "thread_broadcast", "me_message"}


def _clean_slack_text(text: str, users: dict[str, str]) -> str:
    text = re.sub(r"<@([A-Z0-9]+)(?:\|([^>]+))?>",
                  lambda m: "@" + (m.group(2) or users.get(m.group(1), m.group(1))), text)
    text = re.sub(r"<#[A-Z0-9]+\|([^>]+)>", r"#\1", text)
    text = re.sub(r"<!(here|channel|everyone)>", r"@\1", text)
    text = re.sub(r"<([^>|]+)\|([^>]+)>", r"\2", text)
    text = re.sub(r"<((?:https?|mailto):[^>]+)>", r"\1", text)
    return " ".join(html.unescape(text).split())


def _slack_events(messages: Iterable[dict], users: dict[str, str], origin: str) -> list[Event]:
    events = []
    for message in messages:
        if not isinstance(message, dict) or message.get("subtype") not in _KEPT_SUBTYPES:
            continue
        raw = message.get("text") or ""
        if not raw.strip() or "ts" not in message:
            continue
        profile = message.get("user_profile") or {}
        user_id = message.get("user", "")
        actor = (users.get(user_id) or profile.get("real_name") or profile.get("display_name")
                 or message.get("user_name") or message.get("username") or user_id)
        try:
            when = parse_time(message["ts"])
        except InputError as exc:
            raise InputError(f"{origin}: {exc}") from None
        events.append(Event(when, "chat", actor, _clean_slack_text(raw, users)))
    return events


def _user_map(raw_users: object) -> dict[str, str]:
    users = {}
    for user in raw_users if isinstance(raw_users, list) else []:
        if isinstance(user, dict) and user.get("id"):
            profile = user.get("profile") or {}
            users[user["id"]] = (user.get("real_name") or profile.get("real_name")
                                 or user.get("name") or user["id"])
    return users


# Files in a Slack export that describe the workspace rather than hold messages.
_SLACK_METADATA = {"users.json", "channels.json", "groups.json", "dms.json", "mpims.json",
                   "integration_logs.json", "canvases.json"}


def load_slack(path: str | Path) -> list[Event]:
    """Load chat messages from a Slack export.

    Accepts a single JSON file holding a list of messages, an unpacked export
    directory, or the export .zip. A users.json, when present, is used to turn
    user ids into names.
    """
    path = Path(path)
    documents: dict[str, object] = {}
    try:
        if path.is_dir():
            for file in sorted(path.rglob("*.json")):
                documents[file.relative_to(path).as_posix()] = json.loads(file.read_text("utf-8"))
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for name in sorted(archive.namelist()):
                    if name.endswith(".json"):
                        documents[name] = json.loads(archive.read(name).decode("utf-8"))
        else:
            documents[path.name] = json.loads(path.read_text("utf-8"))
    except OSError as exc:
        raise InputError(f"cannot read chat export {path}: {exc}") from None
    except json.JSONDecodeError as exc:
        raise InputError(f"chat export {path} contains invalid JSON: {exc}") from None

    users: dict[str, str] = {}
    for name, document in documents.items():
        if name.rsplit("/", 1)[-1] == "users.json":
            users.update(_user_map(document))
    events: list[Event] = []
    for name, document in documents.items():
        if name.rsplit("/", 1)[-1] in _SLACK_METADATA:
            continue
        if not isinstance(document, list):
            raise InputError(f"{path}: {name} is not a list of messages")
        events.extend(_slack_events(document, users, name))
    return events


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------

_PAGERDUTY_KINDS = {
    "trigger_log_entry": ALERT_TRIGGERED,
    "acknowledge_log_entry": ALERT_ACKNOWLEDGED,
    "resolve_log_entry": ALERT_RESOLVED,
}


def _read_records(path: str | Path, label: str) -> list[dict]:
    """Read a list of records from JSON, JSON Lines or CSV."""
    path = Path(path)
    try:
        text = path.read_text("utf-8-sig")
    except OSError as exc:
        raise InputError(f"cannot read {label} {path}: {exc}") from None
    if path.suffix.lower() == ".csv":
        return [dict(row) for row in csv.DictReader(io.StringIO(text))]
    try:
        if path.suffix.lower() in (".jsonl", ".ndjson"):
            data: object = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{label} {path} contains invalid JSON: {exc}") from None
    if isinstance(data, dict):
        lists = [value for value in data.values() if isinstance(value, list)]
        data = lists[0] if lists else [data]
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise InputError(f"{label} {path}: expected a list of records")
    return data


def _summary(value: object) -> str:
    return str(value.get("summary", "")) if isinstance(value, dict) else str(value or "")


def load_pagerduty(path: str | Path) -> list[Event]:
    """Load a PagerDuty incident log (the `log_entries` JSON for one incident)."""
    events = []
    for entry in _read_records(path, "PagerDuty log"):
        if "created_at" not in entry:
            raise InputError(f"PagerDuty log {path}: entry without created_at")
        entry_type = str(entry.get("type", "")).replace("_reference", "")
        kind = _PAGERDUTY_KINDS.get(entry_type, ALERT_OTHER)
        text = (_summary(entry.get("summary")) or _summary(entry.get("channel"))
                or entry_type.replace("_log_entry", "").replace("_", " "))
        events.append(Event(parse_time(entry["created_at"]), "alert", _summary(entry.get("agent")),
                            text, kind, _summary(entry.get("service"))))
    return events


_ALERT_STATES = {
    "firing": ALERT_TRIGGERED, "triggered": ALERT_TRIGGERED, "open": ALERT_TRIGGERED,
    "alerting": ALERT_TRIGGERED, "critical": ALERT_TRIGGERED,
    "acknowledged": ALERT_ACKNOWLEDGED, "acked": ALERT_ACKNOWLEDGED,
    "resolved": ALERT_RESOLVED, "ok": ALERT_RESOLVED, "closed": ALERT_RESOLVED,
    "recovered": ALERT_RESOLVED,
}


def _first(record: dict, *keys: str) -> str:
    for key in keys:
        if record.get(key) not in (None, ""):
            return str(record[key]).strip()
    return ""


def load_alerts(path: str | Path) -> list[Event]:
    """Load a generic alert log: CSV, JSON or JSON Lines.

    Each record needs a time (`time`/`timestamp`), a name (`name`/`alert`/
    `summary`) and a `state` such as firing, acknowledged or resolved.
    """
    events = []
    for number, record in enumerate(_read_records(path, "alert log"), start=1):
        when = _first(record, "time", "timestamp", "created_at")
        name = _first(record, "name", "alert", "alertname", "summary")
        if not when or not name:
            raise InputError(f"alert log {path}: record {number} needs a time and a name")
        state = _first(record, "state", "status").lower()
        kind = _ALERT_STATES.get(state, ALERT_OTHER)
        severity = _first(record, "severity")
        text = f"{name} [{severity}]" if severity else name
        if kind == ALERT_OTHER and state:
            text += f" ({state})"
        events.append(Event(parse_time(when), "alert", _first(record, "actor", "user"), text,
                            kind, _first(record, "service")))
    return events


# --------------------------------------------------------------------------
# Deploys
# --------------------------------------------------------------------------

def load_deploys(path: str | Path) -> list[Event]:
    """Load deploy events: CSV, JSON or JSON Lines.

    Each record needs a time and a `service`; `version`, `action` (deploy or
    rollback), `environment` and `actor` are optional.
    """
    events = []
    for number, record in enumerate(_read_records(path, "deploy log"), start=1):
        when = _first(record, "time", "timestamp", "deployed_at")
        service = _first(record, "service", "app", "application")
        if not when or not service:
            raise InputError(f"deploy log {path}: record {number} needs a time and a service")
        action = _first(record, "action", "type", "event").lower() or "deploy"
        kind = ROLLBACK if "rollback" in action or "revert" in action else DEPLOY
        version = _first(record, "version", "release", "sha")
        environment = _first(record, "environment", "env")
        text = ("Rollback of " if kind == ROLLBACK else "Deploy of ") + service
        if version:
            text += f" {'to ' if kind == ROLLBACK else ''}{version}"
        if environment:
            text += f" ({environment})"
        events.append(Event(parse_time(when), "deploy", _first(record, "actor", "user", "author"),
                            text, kind, service))
    return events
