from datetime import datetime, timedelta, timezone

import pytest

from ai_postmortem.ingest import (ALERT_ACKNOWLEDGED, ALERT_RESOLVED, ALERT_TRIGGERED, DEPLOY,
                                  NOTE, ROLLBACK, Event)
from ai_postmortem.timeline import (ACTION_ITEM, CAUSE, DETECTION, FACTOR, IMPACT, MITIGATION,
                                    RESOLUTION, anonymise, build_timeline, classify, find_milestones)


def at(minute, source="chat", text="", kind=NOTE, actor=""):
    return Event(datetime(2026, 3, 14, 14, 0, tzinfo=timezone.utc) + timedelta(minutes=minute),
                 source, actor, text, kind)


@pytest.mark.parametrize("text, kind", [
    ("AI: add an alert on pool saturation", ACTION_ITEM),
    ("We should add a canary stage", ACTION_ITEM),
    ("Incident resolved, thanks all", RESOLUTION),
    ("Not resolved yet, errors are still climbing", NOTE),
    ("Rolling back api to v1 now", MITIGATION),
    ("Should we roll back?", NOTE),
    ("we haven't restarted anything", NOTE),
    ("Turns out the pool size was cut to 5", CAUSE),
    ("There is no alert on queue depth", FACTOR),
    ("About 18% of checkout requests are failing", IMPACT),
    ("Impact: EU region only", IMPACT),
    ("Paged for api 5xx", DETECTION),
    ("grabbing coffee, back in 5", NOTE),
])
def test_classify(text, kind):
    assert classify(text) == kind


def test_build_timeline_sorts_and_classifies_only_chat():
    events = [at(5, text="Rolling back now"), at(1, "alert", "resolved in name", ALERT_TRIGGERED),
              at(5, text="second at same minute")]
    timeline = build_timeline(events)
    assert [e.source for e in timeline] == ["alert", "chat", "chat"]
    assert timeline[0].kind == ALERT_TRIGGERED  # alert text is never reclassified
    assert timeline[1].kind == MITIGATION
    assert timeline[2].text == "second at same minute"  # stable for equal times


def test_anonymise_replaces_actors_and_names_in_text():
    events = [at(1, "alert", "Acknowledged by Ada Example", ALERT_ACKNOWLEDGED, "Ada Example"),
              at(2, text="thanks Ada and @Bo Sample, Adamant is unrelated", actor="Bo Sample"),
              at(3, "deploy", "Rollback of api", ROLLBACK, "Ada Example"),
              at(4, "deploy", "Deploy of api", DEPLOY, "Someone Else")]
    result = anonymise(events)
    assert [e.actor for e in result] == ["Responder 1", "Responder 2", "Responder 1", ""]
    assert result[0].text == "Acknowledged by Responder 1"
    assert result[1].text == "thanks Responder 1 and Responder 2, Adamant is unrelated"


def test_milestones_full_incident():
    timeline = build_timeline([
        at(-200, "deploy", "Deploy of old", DEPLOY),
        at(-4, "deploy", "Deploy of api v2", DEPLOY),
        at(0, "alert", "API down", ALERT_TRIGGERED),
        at(2, "alert", "ack", ALERT_ACKNOWLEDGED),
        at(20, text="Rolling back api"),
        at(22, "deploy", "Rollback of api", ROLLBACK),
        at(30, "alert", "first resolve", ALERT_RESOLVED),
        at(40, "alert", "final resolve", ALERT_RESOLVED),
        at(41, text="Incident resolved"),
    ])
    m = find_milestones(timeline)
    assert m.trigger.text == "Deploy of api v2"
    assert m.detected.text == "API down"
    assert m.mitigated.text == "Rolling back api"
    assert m.resolved.text == "final resolve"
    assert m.between("started", "resolved") == timedelta(minutes=44)
    assert m.between("detected", "acknowledged") == timedelta(minutes=2)
    assert m.between("detected", "mitigated") == timedelta(minutes=20)


def test_milestones_chat_only_and_deploy_window():
    timeline = build_timeline([
        at(-90, "deploy", "Deploy of api v2", DEPLOY),
        at(0, text="customers report errors on login"),
        at(15, text="restarted the auth pods"),
        at(25, text="all clear, incident resolved"),
    ])
    m = find_milestones(timeline)
    assert m.trigger is None and m.acknowledged is None
    assert m.detected.source == "chat"
    assert m.resolved.kind == RESOLUTION
    assert m.between("detected", "resolved") == timedelta(minutes=25)
    wide = find_milestones(timeline, timedelta(minutes=120))
    assert wide.trigger.text == "Deploy of api v2"


def test_milestones_empty_and_unresolved():
    assert find_milestones([]).detected is None
    m = find_milestones([at(0, "alert", "API down", ALERT_TRIGGERED)])
    assert m.resolved is None and m.between("detected", "resolved") is None
