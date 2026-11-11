"""Optional rewording of prose sections by an external text generator.

Nothing here runs unless the caller passes a generator. The interface is one
method, so any model or service can be plugged in; `CommandGenerator` covers
the common case of a local command that reads a prompt on stdin.
"""

from __future__ import annotations

import shlex
import subprocess
from typing import Protocol

PROSE_SECTIONS = ("summary", "impact", "root_cause", "contributing_factors")

PROMPT = """Reword the "{name}" section of an incident postmortem draft.
Rules: keep every fact, time and number exactly as given; add no new facts;
use blameless language (describe systems and decisions, never individuals);
keep the Markdown structure; return only the reworded section.

{text}
"""


class TextGenerator(Protocol):
    def generate(self, prompt: str) -> str:
        """Return generated text for the prompt."""


class CommandGenerator:
    """Send the prompt to a command's stdin and use its stdout as the result."""

    def __init__(self, command: str, timeout: float = 120.0):
        self.argv = shlex.split(command)
        if not self.argv:
            raise ValueError("polish command is empty")
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        result = subprocess.run(self.argv, input=prompt, capture_output=True, text=True,
                                timeout=self.timeout, check=True)
        return result.stdout


def polish_sections(sections: dict[str, str], generator: TextGenerator,
                    names: tuple[str, ...] = PROSE_SECTIONS) -> tuple[dict[str, str], list[str]]:
    """Reword the named sections. Returns the new sections and a list of warnings.

    A section is left untouched when the generator fails or returns nothing,
    so a broken generator can never lose the deterministic draft.
    """
    result = dict(sections)
    warnings = []
    for name in names:
        if not sections.get(name, "").strip():
            continue
        try:
            reworded = generator.generate(PROMPT.format(name=name, text=sections[name])).strip()
        except Exception as exc:  # any generator failure keeps the original text
            warnings.append(f"{name}: generator failed ({exc}); kept the original text")
            continue
        if reworded:
            result[name] = reworded
        else:
            warnings.append(f"{name}: generator returned nothing; kept the original text")
    return result, warnings
