"""Floor gate: SimpleBroker dependency-floor claims must match the manifests.

The package manifests own the runtime floors (`pyproject.toml` for
`simplebroker`, the root optional group plus `extensions/taut_pg/pyproject.toml`
for `simplebroker-pg`). Maintained narrative docs may restate a floor only in
the literal requirement form (``simplebroker>=X.Y.Z`` /
``simplebroker-pg>=X.Y.Z``), and every such restatement must equal the
manifest floor — this is the "README floor equals manifest floor" relation
from the 2026-07-13 release-metadata lesson, extended to specs and
implementation docs after the 2026-08-08 drift (specs said 6.0.1 while the
manifests required 6.0.2).

Historical surfaces are exempt: ``docs/plans/`` (immutable records),
``docs/lessons.md`` and ``docs/coalescing.md`` (dated incident/run logs),
and ``CHANGELOG.md``. Prose mentions of specific historical versions
("Version 5.2.0 supplies the reference ownership model") are provenance,
not floor claims, and are deliberately not matched.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.sqlite_only

REPO_ROOT = Path(__file__).resolve().parent.parent

MAINTAINED_DOCS = sorted(
    [
        REPO_ROOT / "README.md",
        *(REPO_ROOT / "docs" / "specs").glob("*.md"),
        *(REPO_ROOT / "docs" / "implementation").glob("*.md"),
        *REPO_ROOT.glob("extensions/*/README.md"),
    ]
)

# A floor claim is the literal requirement form with a concrete version.
# Placeholders such as ``simplebroker>=X.Y.Z`` or ``simplebroker-pg>=...``
# fail the digit requirement and are not claims.
_CLAIM_RE = re.compile(r"\b(simplebroker(?:-pg)?)>=([0-9][0-9A-Za-z.]*)")


def _requirement_floor(dependencies: list[str], name: str) -> str | None:
    for entry in dependencies:
        match = re.fullmatch(rf"{re.escape(name)}>=([0-9][0-9A-Za-z.]*)", entry)
        if match:
            return match.group(1)
    return None


def _manifest_floors() -> dict[str, str]:
    root = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text("utf-8"))
    pg = tomllib.loads(
        (REPO_ROOT / "extensions" / "taut_pg" / "pyproject.toml").read_text("utf-8")
    )
    simplebroker = _requirement_floor(root["project"]["dependencies"], "simplebroker")
    optional = root["project"].get("optional-dependencies", {})
    root_pg_floor = None
    for group in optional.values():
        root_pg_floor = root_pg_floor or _requirement_floor(group, "simplebroker-pg")
    extension_pg_floor = _requirement_floor(
        pg["project"]["dependencies"], "simplebroker-pg"
    )
    assert simplebroker is not None, "root manifest must pin a simplebroker floor"
    assert extension_pg_floor is not None, (
        "taut_pg manifest must pin a simplebroker-pg floor"
    )
    if root_pg_floor is not None:
        assert root_pg_floor == extension_pg_floor, (
            "root optional simplebroker-pg floor and the taut_pg extension "
            f"manifest disagree: {root_pg_floor} != {extension_pg_floor}"
        )
    return {"simplebroker": simplebroker, "simplebroker-pg": extension_pg_floor}


def test_doc_floor_claims_match_manifests() -> None:
    floors = _manifest_floors()
    mismatches: list[str] = []
    for doc in MAINTAINED_DOCS:
        text = doc.read_text("utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, version in _CLAIM_RE.findall(line):
                if version != floors[name]:
                    mismatches.append(
                        f"{doc.relative_to(REPO_ROOT)}:{lineno}: "
                        f"claims {name}>={version}, manifest floor is "
                        f"{name}>={floors[name]}"
                    )
    assert not mismatches, "stale dependency-floor claims:\n" + "\n".join(mismatches)


def test_scanner_sees_known_claim_surfaces() -> None:
    """The gate is only as good as its scan set: the surfaces that carried
    floor claims when this gate landed must still be scanned and still carry
    at least one claim each, so a file rename cannot silently empty the gate."""
    expected = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "specs" / "02-taut-core.md",
        REPO_ROOT / "docs" / "specs" / "03-identity-addressing-notifications.md",
        REPO_ROOT / "docs" / "specs" / "04-summon.md",
        REPO_ROOT / "docs" / "implementation" / "04-taut-architecture.md",
        REPO_ROOT / "docs" / "implementation" / "05-taut-summon-architecture.md",
    ]
    for doc in expected:
        assert doc in MAINTAINED_DOCS, f"{doc} left the scan set"
        assert _CLAIM_RE.search(doc.read_text("utf-8")), (
            f"{doc.relative_to(REPO_ROOT)} no longer carries a literal floor "
            "claim; update this fixture list if that is intentional"
        )
