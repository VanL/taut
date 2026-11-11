# Agent Theory and Program Theory

Status: Reference — definitional primer
Owner: agent-theory maintainers (definitions); product owners (their own
`docs/program-theory.md` account)
Boundary: Explains what **Agent Theory** and **program theory** mean, how they
differ from behavioral specs and process rules, and where to read next. This
file is a reference primer — it is **not** the program theory of any product,
**not** a behavioral contract, and **not** required reading at every session
start.
Verification: Consistency with this repository's `docs/program-theory.md` and
`01-development-documentation-operating-model.md` (this repo) [DOM-2] and [DOM-3].
Required action: Read this file when the terms are unfamiliar, when onboarding
a human or agent to the workflow, or before writing a product theory. Link to
this file rather than re-explaining the definitions in chat.

The `[AT-REF-*]` codes below are citation anchors only; `[DOM-*]` owns the
normative process rules.

---

## What Agent Theory is [AT-REF-1]

**Agent Theory** is a practical discipline for building software with coding
agents while keeping humans in possession of the program's theory: what the
system is, why it has its shape, what it deliberately refuses to do, and how
changes are proved.

Its central rule is simple:

> Humans may delegate implementation, not understanding.

Agent Theory is **not** big design up front. A team's theory of a program
starts partial and sharpens feature by feature through owner dialogue,
specifications, implementation, independent review, and test evidence.

### Three names that are easy to confuse

| Term | Meaning |
|------|---------|
| **Agent Theory** | The engineering discipline (written without a hyphen in prose) |
| **The `agent-theory` hub** (foreign; this file was adopted from it) | The reference repository and starter kit for applying the discipline |
| **`agent-theory`** | The repository slug and command name |

### The failure mode it prevents

Coding agents can produce working code faster than humans can maintain a mental
model of the system. Without deliberate checkpoints, a codebase keeps growing
after neither the human owner nor the agents understand how the whole program
fits together. Agent Theory treats human understanding as a required output of
every change, not an accidental side effect.

### Three foundational ideas

| Author | Core takeaway for Agent Theory |
|--------|--------------------------------|
| **Peter Naur** (*Programming as Theory Building*, 1985) | Programming is the act of building a mental model of the problem and the program. Documentation helps transfer that model, but never replaces a person who holds it. |
| **Donald Knuth** (*Literate Programming*, 1984) | Explanations exist to build human understanding and must stay tied to the working code. Here, separate documents are linked by traceability checks rather than combined into one master file. |
| **Armin Ronacher** (*"The Tower Keeps Rising"*, 2026) | Coding agents remove the everyday friction that used to force teams to agree on shared concepts and boundaries. Deliberate orientation and review checkpoints replace that lost friction. |

---

## What a program theory is [AT-REF-2]

A **program theory** is the working explanatory model of a software system:
what real-world problem it solves, what its core concepts are, who owns each
boundary, what it refuses to build, and what evidence would show the model is
wrong.

Following Peter Naur's *Programming as Theory Building* (1985), a program
theory is **not**:

- a formal mathematical proof,
- a list of user requirements or API endpoints,
- a dump of architecture diagrams, or
- a document that can substitute for human understanding.

### Holding the theory vs. writing the current account

Naur distinguishes between **holding a theory** in your head and **writing a
document** on disk. Agent Theory keeps that distinction explicit:

| Concept | What it means in practice |
|---------|---------------------------|
| **Holding the theory (possession)** | A person's practical ability to place a new feature, explain why the code is shaped the way it is, reject ideas that do not fit the system, and diagnose surprising bugs. |
| **The written account (`docs/program-theory.md`)** | A concise document in the repository that gives humans and zero-context agents the same vocabulary, desired feel (taste up front), boundaries, and non-goals at the start of a task. |

Memorizing `docs/program-theory.md` is not holding the theory. The file gives
humans and agents a shared starting point; day-to-day work with specs, code,
tests, and unexpected bugs is what builds and refreshes the actual mental
model.

You hold the theory of a program when you can do four things:

1. Connect real-world problems to the structure of the code.
2. Explain *why* each major boundary and design choice exists.
3. Place a new feature request without breaking the existing design.
4. Diagnose unexpected behavior when the system or an agent surprises you.

A quick self-test: when the system misbehaves, do you feel *betrayed by an
invariant you know*, or *surprised by a system you do not really own*?

### The four-way balance of a written program theory

Writing a good `docs/program-theory.md` is a balancing act because the document
must do four things at the same time:

1. **Stay general enough that changing implementations remain measurable against
   it.** If you replace an internal algorithm, storage layout, or helper module,
   you should still be able to evaluate the new implementation against the same
   program theory without rewriting the theory first. The concrete instrument for
   that measurement is a **theory-versus-code (and theory-versus-spec) audit
   table**—owned by the product owner, recorded in the crystallization or
   Class-5 plan (or `docs/lessons.md`), run at `skills/crystallize-program-theory`
   confirmation when code or specs already exist, and refreshed at each release
   or Class-5 completion alongside the possession check (carrying forward
   unchanged rows by reference while re-auditing touched claims and
   boundaries)—mapping each theory claim and identity invariant against current
   specs and code as aligned, drifted (to be morphed via a plan), or evidence
   that the theory itself needs revision.
2. **Be specific enough to be more than a list of aphorisms.** Generic advice
   (*"keep it simple"*, *"prefer explicit over implicit"*) cannot tell an agent
   or engineer whether a concrete feature proposal belongs in this program or
   violates its shape.
3. **Record invariants that are core to the identity of the product—the choices
   that shape the entire program.** These **identity (theory-level) invariants**
   are the commitments that make the system what it is across rewrites (for
   example, who owns process lifecycles, where trust boundaries sit, or what
   guarantee never bends for convenience): many parts of the codebase quietly
   depend on them, an agent must not casually "simplify" them away, and if they
   change, the program starts to become something else. They stay distinct from
   the exact wire formats, flags, and state tables in `docs/specs/`.
4. **Record negative knowledge in two parts:**
   - *What the product is not* — category and boundary refusals that stop scope
     creep and overlap with adjacent tools.
   - *What paths were tried and discarded* — empirical dead ends (`[THEORY-5.A*]`),
     so future humans and agents do not spend cycles re-discovering why a
     plausible approach failed.

A useful—though incomplete—analogy is the **Zen of Python** (`PEP 20`). The Zen
of Python came along early enough in Python's development that it guided an
entire generation of developers: it introduced the concept of being *"Pythonic"*
with enough specificity that people could spot non-Pythonic code, while staying
general enough to support a broad ecosystem. Whether a program theory is written
early or after code already exists changes the first work it has to do: written
early (like `PEP 20`), it guides new specs and code as they are built;
crystallized after a codebase has already grown, its immediate job is to audit
existing specs and code against the ideal and surface what needs to be morphed
or cut.

Even so, a product's `docs/program-theory.md` must be **more specific and
fleshed-out than the Zen of Python** for two reasons:

- **A product is narrower and more opinionated than an entire language
   interpreter.** It solves a specific problem with specific boundaries,
   composable operations, and whole-shape commitments.
- **Coding agents have no cultural apprenticeship.** Human Python developers
   learned how to weigh competing aphorisms through years of community review. A
   coding agent starts each session cold; if the tie-breakers, identity
   invariants, and discarded paths are not written down, the agent will use
   generic aphorisms to rationalize whatever local patch it just generated.

### Product theory vs. hub theory

Every repository has one `docs/program-theory.md`, and it always describes
**that repository**:

| Repository | What `docs/program-theory.md` describes |
|------------|-----------------------------------------|
| **A product or library repository** | That product's problem, feel/idiom, composable operations, concepts, ownership boundaries, non-goals, and falsifiers. |
| **The `agent-theory` hub repository** | The guidance system itself (how the process, documents, and gates work). |

When you install the starter kit into a product repository, the installer
writes a short `Status: Stub` file at `docs/program-theory.md`. Replace that
stub with your product's own theory before committing product behavior or
architecture. Never copy the hub's guidance theory into a product repository as
if it were the product's identity.

### Extending the model with module theory

Keep your top-level `docs/program-theory.md` short so every session can read it
in a few minutes. Extending the project theory with a **module theory** file
(typically `<module>/MODULE-THEORY.md` next to that code) is ultimately the
human owner's decision: use one only when a specific module is weakly coupled to
the rest of the program and has theory-level invariants that apply only to that
module—never to excuse a subsystem that diverged from a single whole-program
theory (and never for routine subsystem rules that belong in `docs/specs/` or
`docs/implementation/`). Agents read a module theory only when their task enters
that module, not at every session start.

---

## How program theory differs from other documents [AT-REF-3]

Each document surface in the repository answers a different question:

| Document surface | Question it answers |
|------------------|---------------------|
| **Program theory** (`docs/program-theory.md`, `MODULE-THEORY.md`) | What is the conceptual **ideal** of this system or module? What is its feel/idiom, core composable operations, and **identity invariants** (the choices that shape the entire program)? Why do these concepts, boundaries, non-goals, and discarded paths exist? |
| **Process and operating model** (`[DOM-*]`, `docs/agent-context/`, `skills/`) | How do humans and agents classify tasks, write plans, run reviews, verify changes, and maintain docs? |
| **Product contracts** (`docs/specs/`, authoritative README sections) | What exact behavior, flags, schemas, and **contract invariants** are in the code **right now**? |
| **Implementation docs** (`docs/implementation/`) | Why is the current code structured this way, and where are the key edit points? |
| **Code, tests, and gates** | How does the system run, and what automated checks prove it works? |
| **Plans and decision records** (`docs/plans/`, `[THEORY-5.A*]` / `[REV-*]`) | How are we morphing the code and specs closer to the program theory, and which alternatives were rejected or revised? |

Three directional rules govern how program theory, specs, and plans interact:

- **The program theory is the ideal** — what the software is aiming to be.
- **Specs describe what is currently in the code** — the concrete behavioral
  contract for the current implementation (not an unbuilt wishlist; a spec leads
  the code only across an active plan's spec-promotion slice or when a bug
  violates the contract).
- **Plans morph the code (and the specs) closer to the ideal.**

Note:
1. If the specification or code is pulling away from the theory, the presumption
   is that the specs or code are not properly moored in the theory. If the code
   and the spec disagree, then the presumption is that the code has a bug.
2. Never mistake a current spec or plan for "what has been decided" and try to
   justify it when it falls short of the theory. Everything—including the theory
   itself (`[REV-*]`)—can be revised as implementation and experience teach us
   more. When a spec clause itself is stale or when experience building and
   operating the code suggests a better path, then use a plan to fix the spec
   itself.

This file lives in `docs/specs/` as a **reference primer** alongside the
operating-model spec (`01-development-documentation-operating-model.md`). It is
not a behavioral specification for a product.

---

## How theory grows over time [AT-REF-4]

A program theory is built iteratively alongside the software:

```text
concept → owner dialogue → draft theory → spec → implementation
        → test & runtime evidence → revised theory
```

- **Prototype freely on a stub.** While `docs/program-theory.md` is still a
  bootstrap `Stub`, you can explore and prototype, as long as you do not treat
  the stub as product authority.
- **Crystallize before committing product behavior.** Before committing
  product-scope behavior or architecture, interview the owner and write at
  least a `Draft` theory.
- **Communicate program feel ("taste up front") without big design up front.**
  Because coding agents cannot infer unstated aesthetic or ergonomic intent from
  thin air, `docs/program-theory.md` states the product's desired feel, posture,
  and non-goals up front — what using the program should feel like, what makes a
  surface feel native vs. bolted on, and which temptations to refuse. That is
  **taste up front**, not big design up front (BDUF): it gives agents the human
  owner's judgment compass before code is written, while leaving internal
  decomposition, schemas, and feature specs to evolve slice by slice through
  implementation and evidence (`[REV-AT-005]`).
- **Revise when reality pushes back.** Product-scope Class 5 work requires at
  least a current `Draft` account, and that account should be updated whenever
  implementation or debugging reveals a new constraint.

---

## Where to go next [AT-REF-5]

| If you want to... | Read |
|-------------------|------|
| Read this repository's (Taut's) identity account | `docs/program-theory.md` (Status: Active) |
| Write a product or module theory via owner interview | `skills/crystallize-program-theory/SKILL.md` |
| Check how agents load context at session start | `01-development-documentation-operating-model.md` (this repo) [DOM-2], [DOM-3] |
| Read the human overview | Root `README.md` |
| Install the starter kit into another repo (hub only) | The `agent-theory` bootstrap command (`bootstrap-agent-theory`) |
| See which repositories use these practices | Root `README.md` in the `agent-theory` repository (factual links, not efficacy claims) |

---

## Related Plans

- `docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md`
  — propagates the four-way balance of written program theory, theory-versus-code
  audit table, human-decided module-theory boundary, and three directional rules
  from `agent-theory` @ `e6ac579`
- `docs/plans/2026-10-14-agent-theory-delta-wave-plan.md` — propagates the
  STE100 readability rewrite and taste-up-front boundary (`[REV-AT-005]`) of
  `[AT-REF-1]`–`[AT-REF-5]` from the `agent-theory` hub @ `296a7cd`
- retired: 2026-08-07-agent-theory-delta-wave-plan — adopted here by that plan
  (this repo; source `4e3f12f`; see the ledger in `docs/plans/README.md`) from
  the agent-theory hub @ `0423923`; the hub's authoring plan
  is "2026-07-30-program-theory-and-module-theory" (agent-theory repo)
