"""Persona-template tests: the [SUM-10] default system prompt.

Contract under test: docs/specs/04-summon.md [SUM-10] (the default
template states the six mandatory elements, parameterized by member name,
joined threads, workspace path, and provider) and [SUM-6] (the mouth
contract the template must make explicit).
"""

from __future__ import annotations

from taut_summon._persona import render_default_persona

# Independent [SUM-10] oracle.  Do not derive this inventory from the
# renderer: changing the product's list must not silently change the test's
# definition of a complete persona.
REQUIRED_PERSONA_CONCEPTS: dict[str, tuple[str, ...]] = {
    "## Your mouth: how you speak": (
        "taut cli",
        "taut_token",
        "discovers the project",
        "path-addressed backend",
        "stdout is not speech",
        "silence",
        "not a newline",
        "stdin",
    ),
    "## Your ears: how messages arrive": (
        "[#general]",
        "[dm]",
        "[notify]",
        "mid-task",
    ),
    "## Interrupts: messages that arrive mid-task": (
        "act on it now",
        "defer it",
        "push back",
        "never silently absorb",
    ),
    "## Silence is a normal outcome": (
        "normal, common outcome",
        "low bar",
        "no obligation to narrate",
    ),
    "## Loop discipline": (
        "another agent's message unless it mentions you or asks",
        "work products",
        "driver-side rate backstop",
        "low-rate semantic loop",
    ),
    "## Chat trust and authority": (
        "user-role workspace input",
        "claiming to be system policy is not thereby trusted",
        "operator's authority policy",
        "authorization boundary",
    ),
}


def _render() -> str:
    return render_default_persona(
        name="reviewer",
        threads=("dev", "ops"),
        workspace="/work/.taut.db",
        provider="claude",
    )


def test_template_contains_all_mandatory_sections() -> None:
    prompt = " ".join(_render().lower().split())
    for heading, required_concepts in REQUIRED_PERSONA_CONCEPTS.items():
        assert heading.lower() in prompt, f"missing mandatory section: {heading}"
        for concept in required_concepts:
            assert concept in prompt, f"{heading} does not explain {concept!r}"


def test_template_substitutes_all_parameters() -> None:
    prompt = _render()
    # member name, provider, joined threads, workspace path.
    assert "'reviewer'" in prompt
    assert "claude" in prompt
    assert "#dev, #ops" in prompt
    assert "/work/.taut.db" in prompt


def test_default_thread_when_none_given() -> None:
    prompt = render_default_persona(
        name="claude", threads=(), workspace="/x.db", provider="claude"
    )
    assert "#general" in prompt
