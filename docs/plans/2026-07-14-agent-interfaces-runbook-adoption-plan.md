# Agent-Interfaces Runbook Adoption (Mini-Wave)

Status: completed — landed 2026-07-14
Class: 3+P (effective 5) — adopting a runbook that shapes how future
agent-facing surfaces are designed and reviewed; immediately relevant
to the active `2026-07-14-taut-mcp-extension-plan.md` (MCP tool design
is squarely this runbook's subject). Hardening: N/A — no risky trigger
(one runbook + registration rows). Pre-landing review: content passed
a grok round in the source repo today; a second grok round, scoped to
the adaptations and shared with the mm landing, is the +P review —
dispositions in §4.

## 1. Goal

Adopt `docs/agent-context/runbooks/designing-agent-facing-interfaces.md`
from agent-guidance @ `a4b4345` (first [DOM-14] fold-up, distilled from
mm's agent API design). Early adoption ahead of the next full wave so
the MCP extension plan's tool surface can be reviewed against it.

## 2. Adaptations

Minimal — this repo's engineering-principles numbering matches the
canonical (§2 canonicalize, §12 enumerable), so principle citations
land verbatim. Changes: adoption provenance line; the hub plan path
cited as a foreign path; `context.index.yaml` row; Active Plans bullet.
Landing note: `docs/plans/README.md` is dirty with this repo's own WIP
(the MCP plan row) — staged via a synthetic HEAD+mine blob so the WIP
stays uncommitted, per the staging-safety lessons.

## 3. Verification

- Runbook present; this repo's doc-reference tests green; citations
  grep-checked.

## 4. Review Findings and Dispositions

Shared scoped round (grok, 2026-07-14, run in mm with this repo's
adaptation embedded verbatim plus this repo's actual §2/§12 headings;
`stopReason: EndTurn`): **PASS**, no P1/P2. Verified for this repo:
keeping the hub's § citations is the right strategy (numbering matches
canonical — §12 exact-title match; §2 stem match with unambiguous
identity, noted as P3 wording shorthand, no change needed), and the
provenance lines are correct in form (foreign hub plan path, `a4b4345`
pin, local adoption plan path).
