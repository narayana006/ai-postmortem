import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from ai_postmortem.cli import main
from ai_postmortem.draft import (TemplateError, build_sections, format_duration, load_template,
                                 render)
from ai_postmortem.ingest import load_deploys, load_pagerduty, load_slack
from ai_postmortem.polish import CommandGenerator, polish_sections
from ai_postmortem.timeline import anonymise, build_timeline, find_milestones

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
INPUTS = ["--slack", str(EXAMPLES / "slack-export"), "--pagerduty", str(EXAMPLES / "pagerduty-log.json"),
          "--deploys", str(EXAMPLES / "deploys.csv")]


@pytest.fixture()
def sections():
    events = (load_slack(EXAMPLES / "slack-export") + load_pagerduty(EXAMPLES / "pagerduty-log.json")
              + load_deploys(EXAMPLES / "deploys.csv"))
    timeline = anonymise(build_timeline(events))
    return build_sections(timeline, find_milestones(timeline))


@pytest.mark.parametrize("seconds, text", [(47, "47s"), (240, "4m"), (3600, "1h"), (4020, "1h 7m"),
                                           (90000, "1d 1h")])
def test_format_duration(seconds, text):
    assert format_duration(timedelta(seconds=seconds)) == text
    assert format_duration(None) == "unknown"


def test_sections_from_example(sections):
    assert sections["title"] == "checkout-api 5xx error rate above 5% for 2 minutes"
    assert "from about 13:58 to 14:44 UTC (46m)" in sections["summary"]
    assert "Deploy of checkout-api v2.41.0 (production) at 13:58 UTC shipped 4m before" in sections["summary"]
    assert "18% of checkout requests" in sections["impact"]
    assert "pool size was cut from 50 to 5" in sections["root_cause"]
    assert "no alert on pool saturation" in sections["contributing_factors"]
    assert sections["action_items"].count("| TBD | TBD |") == 3
    assert "| 1 | add an alert on database connection pool saturation" in sections["action_items"]
    assert "| Time to resolve | 42m |" in sections["metrics"]


def test_draft_is_blameless_by_default(sections):
    text = "\n".join(sections.values())
    for name in ("Priya", "Tomas", "Mei", "Raman"):
        assert name not in text
    assert "Responder 1" in text


def test_sections_with_nothing_recognised_ask_for_input():
    from ai_postmortem.ingest import Event, parse_time
    timeline = build_timeline([Event(parse_time("2026-03-14T14:00:00Z"), "chat", "A", "hello")])
    sections = build_sections(timeline, find_milestones(timeline))
    for name in ("impact", "root_cause", "trigger", "action_items", "resolution"):
        assert sections[name].startswith("_Needs input:_"), name
    assert "first raised by a person in chat" in sections["contributing_factors"]


def test_render_custom_template_and_errors(sections, tmp_path):
    assert render("# $title costs $$5\n\n$summary", sections).startswith(
        "# checkout-api 5xx error rate above 5% for 2 minutes costs $5\n")
    with pytest.raises(TemplateError, match=r"unknown field \$owner"):
        render("$owner", sections)
    with pytest.raises(TemplateError, match="unknown template"):
        load_template(str(tmp_path / "nope.md"))
    assert "## Leadup" in load_template("atlassian")


def test_cli_draft_matches_committed_example(capsys):
    assert main(["draft", *INPUTS]) == 0
    assert capsys.readouterr().out == (EXAMPLES / "draft-google-sre.md").read_text("utf-8")


def test_cli_templates_names_and_output_file(tmp_path, capsys):
    out = tmp_path / "pm.md"
    assert main(["draft", *INPUTS, "--template", "atlassian", "--people", "names",
                 "--title", "Checkout errors", "-o", str(out)]) == 0
    text = out.read_text()
    assert text.startswith("# Incident postmortem: Checkout errors\n")
    assert "Priya Raman" in text and "## Corrective actions" in text
    assert main(["draft", *INPUTS, "--template", str(EXAMPLES / "custom-template.md")]) == 0
    assert "## What customers saw" in capsys.readouterr().out


def test_cli_timeline_json_and_full(capsys):
    assert main(["timeline", *INPUTS, "--json"]) == 0
    key_events = json.loads(capsys.readouterr().out)
    assert key_events[0] == {"time": "2026-03-14T11:20:00+00:00", "source": "deploy", "kind": "deploy",
                             "actor": "", "text": "Deploy of search-api v1.9.2 (production)"}
    assert all(e["kind"] != "note" for e in key_events)
    assert main(["timeline", *INPUTS, "--json", "--full-timeline"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 21 > len(key_events)


def test_cli_errors(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["draft"])
    assert exit_info.value.code == 2
    assert main(["draft", "--deploys", str(tmp_path / "missing.csv")]) == 2
    assert "cannot read deploy log" in capsys.readouterr().err
    empty = tmp_path / "empty.json"
    empty.write_text("[]")
    assert main(["draft", "--slack", str(empty)]) == 1


class FakeGenerator:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if '"impact"' in prompt:
            return "   "
        if '"root_cause"' in prompt:
            raise RuntimeError("service unavailable")
        return "REWORDED"


def test_polish_uses_generator_and_keeps_text_on_failure(sections):
    fake = FakeGenerator()
    polished, warnings = polish_sections(sections, fake)
    assert polished["summary"] == "REWORDED"
    assert polished["impact"] == sections["impact"]
    assert polished["root_cause"] == sections["root_cause"]
    assert polished["timeline"] == sections["timeline"]  # tables are never sent
    assert len(fake.prompts) == 4 and sections["summary"] in fake.prompts[0]
    assert len(warnings) == 2 and "service unavailable" in warnings[1]


def test_polish_command_end_to_end(capsys):
    command = f'{sys.executable} -c "import sys; sys.stdin.read(); print(\'Reworded by command.\')"'
    assert main(["draft", *INPUTS, "--polish-command", command]) == 0
    assert "## Summary\n\nReworded by command.\n" in capsys.readouterr().out
    assert CommandGenerator("cat").generate("echo me") == "echo me"
    with pytest.raises(ValueError):
        CommandGenerator("  ")
