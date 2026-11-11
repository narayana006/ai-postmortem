import json
import zipfile
from datetime import datetime, timezone

import pytest

from ai_postmortem.ingest import (ALERT_ACKNOWLEDGED, ALERT_OTHER, ALERT_RESOLVED, ALERT_TRIGGERED,
                                  DEPLOY, ROLLBACK, InputError, load_alerts, load_deploys,
                                  load_pagerduty, load_slack, parse_time)

UTC = timezone.utc
USERS = [{"id": "U1", "name": "ada", "real_name": "Ada Example"},
         {"id": "U2", "name": "bo", "profile": {"real_name": "Bo Sample"}}]
MESSAGES = [
    {"type": "message", "subtype": "channel_join", "user": "U1", "ts": "1773496800.000001",
     "text": "<@U1> has joined the channel"},
    {"type": "message", "user": "U1", "ts": "1773496860.000002",
     "text": "cc <@U2> see <https://status.example.com|status page> &amp; <#C9|ops>"},
    {"type": "message", "user": "U2", "ts": "1773496920.000003", "text": "   "},
    {"type": "message", "user": "U9", "ts": "1773496980.000004", "text": "unknown user here"},
]


def test_parse_time_accepts_iso_epoch_and_naive():
    expected = datetime(2026, 3, 14, 14, 0, tzinfo=UTC)
    assert parse_time("2026-03-14T14:00:00Z") == expected
    assert parse_time("2026-03-14T15:00:00+01:00") == expected
    assert parse_time("2026-03-14 14:00:00") == expected
    assert parse_time("1773496800.000100").replace(microsecond=0) == expected
    assert parse_time(1773496800) == expected


def test_parse_time_rejects_garbage():
    with pytest.raises(InputError, match="unrecognised timestamp"):
        parse_time("last Tuesday")


def test_slack_single_file_skips_joins_and_blank_messages(tmp_path):
    path = tmp_path / "channel.json"
    path.write_text(json.dumps(MESSAGES))
    events = load_slack(path)
    assert [e.actor for e in events] == ["U1", "U9"]
    assert events[0].time.replace(microsecond=0) == datetime(2026, 3, 14, 14, 1, tzinfo=UTC)


def test_slack_directory_resolves_users_and_markup(tmp_path):
    (tmp_path / "inc-1").mkdir()
    (tmp_path / "users.json").write_text(json.dumps(USERS))
    (tmp_path / "channels.json").write_text(json.dumps([{"id": "C1", "name": "inc-1"}]))
    (tmp_path / "inc-1" / "2026-03-14.json").write_text(json.dumps(MESSAGES))
    events = load_slack(tmp_path)
    assert events[0].actor == "Ada Example"
    assert events[0].text == "cc @Bo Sample see status page & #ops"


def test_slack_zip_export(tmp_path):
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("users.json", json.dumps(USERS))
        zf.writestr("inc-1/2026-03-14.json", json.dumps(MESSAGES))
    events = load_slack(archive)
    assert len(events) == 2 and events[0].actor == "Ada Example"


def test_slack_errors_are_reported(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(InputError, match="invalid JSON"):
        load_slack(bad)
    bad.write_text('{"messages": 1}')
    with pytest.raises(InputError, match="not a list of messages"):
        load_slack(bad)
    with pytest.raises(InputError, match="cannot read"):
        load_slack(tmp_path / "missing.json")


def test_pagerduty_log_entries(tmp_path):
    path = tmp_path / "pd.json"
    path.write_text(json.dumps({"log_entries": [
        {"type": "trigger_log_entry", "created_at": "2026-03-14T14:02:00Z", "summary": "API down",
         "service": {"summary": "api"}},
        {"type": "acknowledge_log_entry", "created_at": "2026-03-14T14:03:00Z",
         "agent": {"summary": "Ada Example"}},
        {"type": "annotate_log_entry", "created_at": "2026-03-14T14:04:00Z", "summary": "note"},
        {"type": "resolve_log_entry", "created_at": "2026-03-14T14:30:00Z", "summary": "Resolved"},
    ]}))
    events = load_pagerduty(path)
    assert [e.kind for e in events] == [ALERT_TRIGGERED, ALERT_ACKNOWLEDGED, ALERT_OTHER, ALERT_RESOLVED]
    assert events[0].service == "api"
    assert events[1].actor == "Ada Example" and events[1].text == "acknowledge"


def test_generic_alert_log_csv_and_jsonl(tmp_path):
    csv_path = tmp_path / "alerts.csv"
    csv_path.write_text("time,name,state,severity\n"
                        "2026-03-14T14:02:00Z,HighErrors,firing,critical\n"
                        "2026-03-14T14:30:00Z,HighErrors,resolved,\n"
                        "2026-03-14T14:31:00Z,HighErrors,silenced,\n")
    events = load_alerts(csv_path)
    assert [e.kind for e in events] == [ALERT_TRIGGERED, ALERT_RESOLVED, ALERT_OTHER]
    assert events[0].text == "HighErrors [critical]"
    assert events[2].text == "HighErrors (silenced)"

    jsonl = tmp_path / "alerts.jsonl"
    jsonl.write_text('{"timestamp": 1773496800, "alertname": "DiskFull", "status": "firing"}\n')
    assert load_alerts(jsonl)[0].kind == ALERT_TRIGGERED


def test_alert_log_requires_time_and_name(tmp_path):
    path = tmp_path / "alerts.csv"
    path.write_text("time,name,state\n,HighErrors,firing\n")
    with pytest.raises(InputError, match="record 1 needs a time and a name"):
        load_alerts(path)


def test_deploys_csv_and_json(tmp_path):
    csv_path = tmp_path / "deploys.csv"
    csv_path.write_text("time,service,version,action,environment\n"
                        "2026-03-14T13:58:00Z,api,v2,deploy,production\n"
                        "2026-03-14T14:31:00Z,api,v1,rollback,production\n")
    events = load_deploys(csv_path)
    assert [e.kind for e in events] == [DEPLOY, ROLLBACK]
    assert events[0].text == "Deploy of api v2 (production)"
    assert events[1].text == "Rollback of api to v1 (production)"

    json_path = tmp_path / "deploys.json"
    json_path.write_text(json.dumps([{"time": "2026-03-14T13:58:00Z", "service": "api"}]))
    assert load_deploys(json_path)[0].text == "Deploy of api"

    json_path.write_text(json.dumps([{"time": "2026-03-14T13:58:00Z"}]))
    with pytest.raises(InputError, match="needs a time and a service"):
        load_deploys(json_path)
