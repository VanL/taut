# Agent Theory and Program Theory

Status: Reference — definitional primer
Owner: agent-theory maintainers (definition); product owners (their program
theory account)
Boundary: Explains what **Agent Theory** and **program theory** mean, how they
differ from specs and process, and where to look next. This file is **not**
the program theory of any product, **not** a behavioral contract, and **not**
session-start mandatory reading.
Verification: Consistency with this repository's `docs/program-theory.md` and
`01-development-documentation-operating-model.md` (this repo) [DOM-2]/ [DOM-3].
Required action: Read when the terms are unclear, when onboarding a human or
agent to the discipline, or before crystallizing a product theory. Prefer
this file over restating the primer in chat.

Stable codes below are for citation only. They do not create process
obligations the way `[DOM-*]` does.

---

## What Agent Theory is [AT-REF-1]

**Agent Theory** is a practical discipline for building software with coding
agents while keeping humans in possession of the program's theory: what the
system is, why it has its shape, what it deliberately does not do, and how
change is proved.

Central claim:

> Humans may delegate implementation, not understanding.

It is **not** big design up front. Theory begins partial and is refined
feature by feature through dialogue, specification, implementation, review,
and evidence.

### Three names that are easy to conflate

| Name | What it is |
|------|------------|
| **Agent Theory** | The discipline (human brand; no hyphen in prose) |
| **The agent-theory hub repository** (foreign; this file was adopted from it) | The reference operating model and starter corpus for applying the discipline |
| **`agent-theory`** | Repository slug and path/command name |

### Failure mode it addresses

Coding agents can decouple construction from understanding. A codebase may
keep growing while neither humans nor agents share a coherent account of the
whole. Agent Theory treats human understanding as a deliverable of
agent-assisted development, not a private side effect that might survive the
next refactor.

### Intellectual lineage (short)

| Source | Takeaway |
|--------|----------|
| **Naur** — programming as theory building | Docs are secondary to *possession* of the working model |
| **Knuth** — literate programming | Explanation for understanding, kept in contact with realization (here via linked surfaces, not one master file) |
| **Ronacher** — “The Tower Keeps Rising” | Shared language is scarce under AI assistance; construction can continue after understanding has already collapsed |

---

## What program theory is [AT-REF-2]

**Program theory** is the working explanatory model of a program (or of a
guidance system): the problem world, core concepts, ownership, non-goals, and
what would show the model is wrong.

It follows Peter Naur's *Programming as Theory Building* (1985). It is **not**:

- a formal mathematical theory,
- a synonym for requirements or API docs,
- an architecture diagram dump,
- a substitute for possessing the model in practice.

### Possession vs current account

| | |
|--|--|
| **Possession** | Practical: place a demand, justify shape, refuse category errors, diagnose surprises |
| **Current account** | Written transfer surface (`docs/program-theory.md` in a product repo) so agents and humans share language |

Memorizing the file is not possession. The file orients; practice rebuilds the
full working theory with contracts, code, tests, and surprises.

Someone has the theory when they can:

- relate world affairs to program shape,
- justify why that shape exists,
- place a new demand without losing coherence,
- diagnose surprises that do not fit.

A useful self-probe: when the system misbehaves, does it feel like *betrayed
by an invariant I know* or *surprised by a system I don't own*?

### Product theory vs hub theory

| Location | File describes |
|----------|----------------|
| **Product / library repository** | That product's problem, concepts, ownership, non-goals, falsifiers |
| **The agent-theory hub repository** | The guidance system itself (process + meta-theory) |

After bootstrap, consumers replace the stub with **product** theory. Leaving
hub meta-theory as product identity is a category error.

### Module theory

When product theory would become too long, **extend** with **module theory**
next to the owning code (conventional name `MODULE-THEORY.md`). Load it on
**entry** to that module, not on every session start. Do not bulk local depth
into the product theory file.

---

## How theory differs from other surfaces [AT-REF-3]

| Surface | Question it answers |
|---------|---------------------|
| **Program theory** | What kind of system is this? Why these concepts and boundaries? |
| **Process / operating model** (`[DOM-*]`, agent-context, skills) | How do humans and agents plan, review, verify, and keep docs honest? |
| **Product contracts** (specs, winning README sections) | What exact behavior is intended **now**? |
| **Implementation rationale** | Why does the current realization have this shape? |
| **Code and tests / gates** | How is behavior realized, and what evidence fires? |
| **Plans / ALT–REV records** | What change was considered, under which evidence? |

Theory **frames** interpretation and placement. It does **not** override a
winning contract. Contracts must not silently contradict theory; when they
diverge, revise one or the other explicitly.

This primer lives under `docs/specs/` as a **definitional reference** next to
the operating-model contract. It is not itself a product behavioral
specification.

---

## Iterative posture [AT-REF-4]

```text
concept → dialogue → provisional theory → specification → implementation
        → evidence → revised theory
```

- A bootstrap **Stub** is not product authority. Exploration may proceed.
- Begin crystallization before **committing** product-scope behavior or
  architecture.
- Product-scope Class 5 work needs at least a current **Draft** account; the
  account should be revised as implementation exposes new facts.
- Not: full theory before any design. Not: implementation with no articulated
  product model.

---

## Where to go next [AT-REF-5]

| Need | Go to |
|------|--------|
| This repository's (Taut's) identity account | `docs/program-theory.md` (Status: Active) |
| Revising Taut's theory, or writing module theory | `skills/crystallize-program-theory/SKILL.md` |
| How agents load context / taxonomy | `01-development-documentation-operating-model.md` (this repo) [DOM-2], [DOM-3] |
| Human entry | Root `README.md` |
| Install scaffold (hub only) | The agent-theory bootstrap command (`bootstrap-agent-theory`) |
| Provenance and dogfood | Root `README.md` in the agent-theory repository (factual links, not efficacy claims) |

---

## Related Plans

- Adopted here by "2026-08-07-agent-theory-delta-wave-plan" (this
  repo) from the agent-theory hub @ `0423923`; the hub's authoring plan
  is "2026-07-30-program-theory-and-module-theory" (agent-theory repo)
