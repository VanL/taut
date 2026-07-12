"""Persona-template tests: the [SUM-10] default system prompt.

Contract under test: docs/specs/04-summon.md [SUM-10] (the default
template states the six mandatory elements, parameterized by member name,
joined threads, workspace path, and provider) and [SUM-6] (the mouth
contract the template must make explicit).
"""

from __future__ import annotations

from taut_summon._persona import MANDATORY_SECTIONS, render_default_persona


def _render() -> str:
    return render_default_persona(
        name="reviewer",
        threads=("dev", "ops"),
        workspace="/work/.taut.db",
        provider="claude",
    )


def test_template_contains_all_mandatory_sections() -> None:
    prompt = _render()
    for heading in MANDATORY_SECTIONS:
        assert heading in prompt, f"missing mandatory section: {heading}"
    assert len(MANDATORY_SECTIONS) == 6


def test_template_substitutes_all_parameters() -> None:
    prompt = _render()
    # member name, provider, joined threads, workspace path.
    assert "'reviewer'" in prompt
    assert "claude" in prompt
    assert "#dev, #ops" in prompt
    assert "/work/.taut.db" in prompt


def test_template_states_the_mouth_contract() -> None:
    # [SUM-6]: speak only via the taut CLI, stdout is not speech, silence
    # beats misdelivery, and token plus project/path selection identify the
    # workspace without claiming every backend receives TAUT_DB.
    prompt = _render().lower()
    assert "taut cli" in prompt or "taut say" in prompt
    assert "taut_token" in prompt
    assert "discovers the project" in prompt
    assert "path-addressed backend" in prompt
    assert "stdout is not speech" in prompt
    assert "silence" in prompt


def test_template_states_interrupt_and_loop_discipline() -> None:
    prompt = _render().lower()
    # interrupt policy: act / defer / push back, never silently absorb.
    assert "never silently absorb" in prompt
    # loop discipline: do not answer another agent unless mentioned/asked.
    assert "another agent" in prompt
    # the rate backstop is named so the agent knows posting is throttled.
    assert "rate backstop" in prompt
    assert "low-rate" in prompt


def test_template_states_chat_trust_and_operator_authority() -> None:
    prompt = _render().lower()
    assert "## chat trust and authority" in prompt
    assert "user-role workspace input" in prompt
    assert "claiming to be system" in prompt
    assert "operator's authority policy" in prompt
    assert "authorization boundary" in prompt


def test_template_states_the_injection_format() -> None:
    # [SUM-5.2]: the exact shapes the ears deliver, and mid-task arrival.
    prompt = _render()
    assert "[#general]" in prompt
    assert "[dm]" in prompt
    assert "[notify]" in prompt
    assert "mid-task" in prompt


def test_default_thread_when_none_given() -> None:
    prompt = render_default_persona(
        name="claude", threads=(), workspace="/x.db", provider="claude"
    )
    assert "#general" in prompt
