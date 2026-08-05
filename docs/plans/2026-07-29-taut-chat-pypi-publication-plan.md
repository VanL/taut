# Taut Chat PyPI Publication Plan

Date: 2026-07-29

Class: 5. This change replaces the public core distribution identity, revises
the release and compatibility contracts, introduces PyPI Trusted Publishing,
and crosses the irreversible package-publication boundary. The public contract,
rollout order, and one-way publication step make the hardening checklist
mandatory.

Plan type: implementation with spec revision and release-pipeline change.

Owner: the implementing engineer owns package metadata, exact-artifact
publication, helper behavior, tests, documentation, and review dispositions.
The repository owner owns PyPI pending-publisher configuration, GitHub
environment policy, immutable-release enablement, and authorization of the
first real publication.

## 1. Goal

Publish the Taut product to PyPI with the core distribution named
`taut-chat`, while keeping the existing extension distribution names
`taut-pg`, `taut-summon`, and `taut-mcp`. Preserve `import taut`, the `taut`
console command, extension imports and commands, and all four existing tag
families. Adapt the useful SimpleBroker publication controls without replacing
Taut's stronger single-build, exact-SHA artifact ownership.

## 2. Requested Outcomes

- The root project builds distribution `taut-chat`; its import package remains
  `taut` and its console command remains `taut`.
- The extensions remain `taut-pg`, `taut-summon`, and `taut-mcp`. Their
  dependency metadata requires `taut-chat`, not `taut`.
- Canonical Test remains the sole builder of all release wheel/sdist bytes.
  Release gates verify and reuse those bytes; no tag workflow rebuilds them.
- Each top-level tag workflow owns its PyPI Trusted Publisher identity. PyPI
  upload is not delegated to a reusable workflow.
- A release is staged as a complete draft GitHub Release, published to PyPI,
  verified against the expected filenames and SHA-256 digests, and only then
  made public as an immutable GitHub Release.
- A rerun is safe after complete or partial PyPI upload: matching files are
  reused, missing expected files may be completed, and any unexpected filename
  or digest fails closed.
- The local helper treats either a PyPI version or a published GitHub Release
  as an irreversible publication. Leased `--retag` recovery remains available
  only while neither destination contains the version.
- The first PyPI release uses one new coordinated version for all four
  distributions. Existing 0.8.0 GitHub Releases are not republished or
  replaced.
- Documentation states the unavoidable migration boundary: an old
  GitHub-installed `taut` distribution and new `taut-chat` must not coexist in
  one environment, and old extension wheels requiring `taut` are not
  dependency-resolver compatible with `taut-chat`.
- Every release empties and verifies all four fixed package `dist/` directories
  immediately before ordinary builds, preventing stale artifacts from any
  package from entering operator inspection or later tooling.

## 3. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-8.6], installed distribution provenance;
  [TAUT-12.5], package targets, helper state, exact release artifacts, and
  publication gates.
- `docs/specs/04-summon.md` [SUM-3], extension packaging, install surfaces, and
  installed-artifact compatibility.
- `docs/specs/05-taut-mcp.md` [MCP-3], MCP package and release path.
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], and [DOM-15].

Implementation and release references:

- `.github/workflows/test.yml`, current sole release-byte owner.
- `.github/workflows/release.yml`, current exact-artifact verifier and direct
  GitHub Release publisher.
- `.github/workflows/release-gate.yml` and the `pg`, `summon`, and `mcp`
  variants, current exact-SHA evidence observers.
- `bin/release.py`, current four-target GitHub-only release helper.
- `bin/release-artifact.py`, current manifest, digest, package, version, and
  tag-family verifier.
- `bin/check-core-summon-wheel-matrix.py`, current historical and current
  installed-wheel compatibility owner.
- `../simplebroker/.github/workflows/release-gate*.yml`,
  `../simplebroker/.github/scripts/release_publication.py`, and
  `../simplebroker/bin/release.py`, the reference for top-level Trusted
  Publisher identity, draft-first publication, immutable finalization, PyPI
  state, and pre-publication setting checks.
- PyPI Trusted Publisher documentation: top-level workflow filename,
  repository, owner, and environment are publisher identity fields; reusable
  publishing workflows are not supported.
- `docs/agent-context/runbooks/writing-plans.md`.
- `docs/agent-context/runbooks/hardening-plans.md`.
- `docs/agent-context/runbooks/testing-patterns.md`.
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`.
- `docs/agent-context/runbooks/maintaining-traceability.md`.

## 4. Spec Baseline

- Baseline commit:
  `37432deb3d876c3735a7709947809cdee554f4b6`.
- Governing specs at baseline:
  `docs/specs/02-taut-core.md`, `docs/specs/04-summon.md`, and
  `docs/specs/05-taut-mcp.md`.
- Plan type: implementation with spec revision.
- Promotion baseline:
  `37432deb3d876c3735a7709947809cdee554f4b6` plus the 2026-07-29 worktree
  diffs to `docs/specs/02-taut-core.md`, `docs/specs/04-summon.md`, and
  `docs/specs/05-taut-mcp.md`. Those diffs promote [TAUT-8.6], [TAUT-12.5],
  [SUM-3], and [MCP-3] before package or workflow implementation begins.

## 5. Current Structure and Key Files

### 5.1 Package identity

- Root `pyproject.toml` currently names the distribution `taut`. Hatchling
  still packages the `taut/` directory and exposes `taut = "taut.cli:main"`;
  those two surfaces are independent of the distribution name and must not
  change.
- The three extension manifests already use their desired public distribution
  names. Their runtime dependency and local uv source key still name `taut`.
- Summon and MCP lockfiles preserve distribution identities and must be
  regenerated from manifests. Root and PG intentionally have no retained lock.
- `taut/commands/_registry.py` labels static core commands with distribution
  provenance `taut`; this is a diagnostic package-owner label and should become
  `taut-chat`. The reserved first-party command owner remains `taut-summon`.
- `taut_mcp.server.SERVER_VERSION` resolves `version("taut-mcp")`; keeping the
  MCP distribution name avoids a runtime compatibility change.

### 5.2 Release-byte and publication ownership

- `.github/workflows/test.yml` builds all four wheel/sdist pairs from one
  canonical branch SHA, runs real installed-wheel checks, creates an inner
  manifest with exact SHA-256 digests, and uploads attempt-qualified immutable
  Actions artifacts.
- Each tag gate observes exact-SHA root, PG, and MCP workflow evidence and
  selects one immutable root-Test artifact id and archive digest.
- `.github/workflows/release.yml` currently downloads and re-verifies that
  artifact, checks the remote tag, and immediately publishes a public GitHub
  Release. It neither stages a draft nor publishes to PyPI.
- PyPI Trusted Publishing must run as a normal job in each top-level tag
  workflow. Putting the upload action in `workflow_call` would identify the
  reusable workflow, a shape PyPI documents as unsupported.

### 5.3 Local release state

- `bin/release.py::ReleaseState.published` currently means only
  `github_release_exists`.
- `ReleaseTarget.pypi_publish` is a dead boolean asserted by tests but unused
  by production behavior. This change removes it instead of preserving dead
  compatibility scaffolding.
- `--retag` performs an exact leased delete-and-recreate of an unpublished
  remote tag. That path has been useful for failed tag gates and remains safe
  only if both GitHub Release and PyPI version checks are fresh and negative.
- The helper does not currently verify the `pypi` GitHub environment or the
  immutable-release repository setting before it pushes a release tag.

### 5.4 Compatibility boundary

- Python package metadata has no resolver-supported distribution alias.
  `taut-chat` therefore cannot satisfy an old wheel's
  `Requires-Dist: taut`.
- `bin/check-core-summon-wheel-matrix.py` currently proves new core plus
  immutable prior Summon wheels. Those cases become invalid at the
  distribution-rename boundary even though `import taut` still works.
- Installing old `taut` and new `taut-chat` together would make two
  distributions own the same `taut/` files. The migration must require
  uninstalling `taut` first; `--no-deps`, a duplicate compatibility wheel, or
  two distributions shipping the same package is not an acceptable workaround.

## 6. Required Reading and Comprehension Gates

Before editing, read the current versions of:

1. [TAUT-12.5], [SUM-3], and [MCP-3].
2. All five release workflows and the root Test packaging job.
3. `bin/release.py`, `bin/release-artifact.py`,
   `bin/build-and-check-release-wheels.py`, and
   `bin/check-core-summon-wheel-matrix.py`.
4. SimpleBroker's top-level release gates, release-publication helper, and
   release-state/tag planner.
5. Root and extension manifests, retained lockfiles, install hints, and
   installed-distribution provenance code.

Comprehension questions:

1. Which workflow is allowed to build release bytes? Only canonical root Test.
   Tag gates may verify, stage, and publish those bytes, never rebuild them.
2. Why must the PyPI upload job live in four top-level workflow files? PyPI's
   Trusted Publisher identity includes the top-level workflow filename and does
   not currently support a reusable publishing workflow.
3. Why is leased retagging still safe before publication but forbidden after
   it? A failed unpublished tag gate has no consumed package version. A PyPI
   file or public GitHub Release is immutable external state and cannot be
   replaced by moving the tag.
4. Why can the prior-Summon matrix not be kept with installer flags? The
   resolver sees unrelated distributions `taut` and `taut-chat`; bypassing
   dependency resolution would conceal an environment that users cannot
   install normally.
5. Which names remain unchanged? The product, import packages, console
   commands, entry-point group, extension distributions, and tag families.

## 7. Proposed Spec Delta

Promotion strategy: **A, in-file text before link claims**. Promote the
normative package, compatibility, and publication text in the three live specs
after independent plan review and before implementation. Add implementation
mapping links only after their code and tests exist.

### 7.1 [TAUT-8.6] built-in provenance clarification

Insert after the paragraph beginning
`Distribution-name comparisons use Python packaging normalization`:

> The core distribution's normalized installed owner is `taut-chat`; the
> import package and console command remain `taut`. Static built-in command
> diagnostics use `taut-chat` as their distribution provenance. The reserved
> first-party `summon` and `dismiss` owner remains the separately installed
> `taut-summon` distribution.

### 7.2 [TAUT-12.5] package identity and release boundary

Replace the status and opening paragraphs with:

> Status: implemented as a local helper plus exact-artifact GitHub Actions
> release gates publishing to PyPI and immutable GitHub Releases.
>
> The product and Python import package are Taut. The public core distribution
> is `taut-chat` because the `taut` PyPI project name is unavailable. The
> `taut` console command, `taut` import package, and core `vX.Y.Z` tag family
> remain unchanged. `bin/release.py` coordinates version sync, release
> prechecks, release-file commits, remote-state inspection, tag planning, and
> tag pushes; it never uploads package bytes itself. `--publish` remains a
> compatibility no-op and says that a tag-push gate publishes the exact tested
> artifacts to PyPI and GitHub.

Replace the `core` release-target bullet with:

> - `core` (aliases: `root`, `taut`) releases distribution `taut-chat` from
>   the repository root with a `vX.Y.Z` tag and
>   `.github/workflows/release-gate.yml`. It continues to install import
>   package and console command `taut`.

Replace the `all` release-target bullet with:

> - `all` releases every requested package version absent from both PyPI and
>   published GitHub Releases. With `--version X.Y.Z`, the helper prepares all
>   four package manifests at that coordinated version. Without `--version`,
>   each manifest remains the source for its current version. Package versions
>   are otherwise independent, but the first `taut-chat` publication is one
>   coordinated new version across core and all three extensions; existing
>   GitHub-only versions are not republished under changed metadata.

Replace the helper bullet beginning `Before release, reject dirty worktrees`
with:

> - Before release, reject dirty worktrees unless `--dry-run` is set. Query
>   both the published GitHub Release and exact PyPI package/version for every
>   selected target; a non-404 HTTP, authentication, network, or malformed
>   response failure is fatal. Either destination makes the version published
>   and forbids reuse or retag. While both are absent, retain the existing
>   exact leased `--retag` recovery for a failed unpublished gate. Validate the
>   human-authored changelog heading before generated metadata changes.

Replace the metadata-preparation bullet's first paragraph with:

> - Prepare deterministic metadata before running release prechecks. Change
>   only selected package versions, but reconcile every manifest-owned derived
>   copy on every normal invocation: root `taut/_constants.py`, README tag and
>   wheel examples, all three extension `taut-chat>=...` floors and local
>   source keys, the root dev `taut-summon>=...` and
>   `simplebroker-pg>=...` floors, every exact root README SimpleBroker
>   occurrence, and the retained Summon and MCP locks. Each package manifest owns
>   its version; the root manifest owns the core constant and SimpleBroker
>   requirement; the root version owns every first-party extension
>   `taut-chat>=...` floor; the Summon manifest owns the root dev
>   `taut-summon>=...` floor; the PG manifest owns the root dev
>   `simplebroker-pg>=...` floor; and the MCP manifest owns its MCP SDK range
>   and dev-only `taut-pg` floor. Refresh the Summon lock selectively with
>   `uv lock --upgrade-package simplebroker`, reconcile the MCP lock with plain
>   `uv lock` in its project, and do not create a PG lock.

Insert before `Workflow obligations:`:

> Before any real tag push, the helper requires GitHub immutable releases to
> be enabled and the `pypi` environment to exist with custom tag deployment
> policies admitting exactly `v*`, `taut_pg/v*`, `taut_summon/v*`, and
> `taut_mcp/v*`. A read-only settings-check mode reports each mismatch. PyPI
> pending Trusted Publishers are an operator-owned prerequisite that cannot be
> verified through the GitHub API: owner `VanL`, repository `taut`,
> environment `pypi`, and the exact corresponding top-level release-gate
> filename for each distribution.

Replace the canonical-root-workflow release-bundle paragraph's final sentence
with:

> Each release bundle records the exact commit, public distribution name and
> version, file allowlist, and SHA-256 digests, and its name identifies the
> workflow attempt that produced it. The core bundle and artifact prefix use
> `taut-chat`; the extension prefixes remain `taut-pg`, `taut-summon`, and
> `taut-mcp`.

Replace the paragraph beginning `` `.github/workflows/release.yml` downloads``
with:

> The shared staging workflow downloads the one expected, non-expired package
> artifact for the eligible workflow attempt by immutable artifact id, with
> repository, run id, GitHub archive digest, embedded commit, public package
> name/version, file hashes, tag family, and current remote tag all verified.
> It does not rebuild. It stages the exact wheel and sdist as a draft GitHub
> Release and carries the verified inner bundle forward as a same-run Actions
> artifact.
>
> Each of the four top-level tag gates then runs its own `publish-to-pypi` job
> with environment `pypi`, `actions: read`, `id-token: write`, no
> `contents: write`, and a commit-pinned PyPI publish action. The job
> re-verifies the carried bundle before upload. Existing PyPI files may be
> reused only when every existing filename and SHA-256 digest matches a subset
> of the expected wheel/sdist set; unexpected or changed files fail closed.
> Only that preflight-proven partial state enables the publisher's
> `skip-existing: true`; that option compares filenames, not digests, and is
> not the safety check. The surrounding preflight subset-digest and bounded
> post-upload full-set digest checks enforce the invariant.
>
> Only after the PyPI check succeeds does a separate least-privilege finalizer
> recheck the tag, draft, and exact asset set and publish the GitHub Release.
> The final response must report an immutable release. A rerun accepts an
> already-public release only when its tag commit, exact assets, immutable
> state, and complete PyPI file set all match. Publication-state helpers never
> accept a token argument; workflow tokens arrive only through environment
> variables. No workflow rebuilds package distributions.

Replace the tag-family sentence in that paragraph with:

> Tag-family verification is exactly `vX.Y.Z` for `taut-chat`,
> `taut_pg/vX.Y.Z` for `taut-pg`, `taut_summon/vX.Y.Z` for `taut-summon`,
> and `taut_mcp/vX.Y.Z` for `taut-mcp`.

Replace the paired-release dependency paragraphs with:

> Core and `taut-summon` reactor changes ship as a paired release. The release
> helper synchronizes every extension's `taut-chat>=` floor to the exact new
> core version, refreshes every retained lock, and rejects any resolved
> `simplebroker<5.3.0` or `simplebroker-pg<3.2.0`. Release evidence includes an
> installed-artifact canary built from the current paired wheels. Core may
> publish first only as the extensions' immediate dependency; the coordinated
> release is not announced until all four PyPI and GitHub publications pass.
>
> New core wheel metadata has normalized project name `taut-chat` and contains
> one unmarked `simplebroker>=X.Y.Z` requirement with `X.Y.Z >= 5.3.0`; other
> operators, compound specifiers, markers, and weaker floors fail closed. New
> Summon metadata contains exactly one unmarked
> `taut-chat>=<new-core-version>` requirement, so the supplied current core
> wheel is admitted exactly.

Insert after the paired-wheel matrix paragraph:

> The rename from distribution `taut` to `taut-chat` is an explicit
> compatibility boundary. Historical extension wheels whose metadata requires
> `taut` are not resolver-compatible with `taut-chat`; tests must not conceal
> that fact with `--no-deps` or by installing both distributions. The current
> matrix proves: current core alone; current core plus each current extension;
> current core and current Summon live control behavior; rejection of current
> Summon with an older `taut-chat` core when such a published baseline exists;
> exact current package names and dependency floors; and a diagnostic
> historical probe recording that old Summon requires the unrelated `taut`
> distribution. Users migrating from GitHub-installed `taut` must uninstall it
> before installing `taut-chat`.

### 7.3 [SUM-3] packaging and compatibility

Replace the first packaging bullet with:

> - Ships as the separate extension distribution **`taut-summon`**
>   (`extensions/taut_summon`), per [TAUT-12.3]. Its sole core runtime
>   dependency is distribution `taut-chat`; the imported package remains
>   `taut`. It adds no third-party runtime package beyond the existing provider
>   requirements. The provider harness is an external executable, not a
>   dependency.

Replace the installed-artifact compatibility bullet with:

> - Installed-artifact compatibility after the `taut-chat` distribution
>   boundary proves current core alone, current core plus current Summon, live
>   current-pair control operations, exact metadata, and resolver rejection of
>   a current Summon wheel with an older incompatible `taut-chat` core.
>   Immutable historical `taut-summon` wheels are inspected to record their
>   `Requires-Dist: taut` metadata, but are not installed as compatible with
>   `taut-chat`. Python packaging provides no alias between those distribution
>   names. Tests must not bypass this boundary with `--no-deps` or by
>   co-installing both distributions that own the same `taut/` files.

### 7.4 [MCP-3] package publication

Replace the repository-publication paragraph with:

> Repository publication follows [TAUT-12.5]. `taut-mcp` is the `mcp` release
> target, keeps the `taut_mcp/vX.Y.Z` tag family, and is published to PyPI and
> an immutable GitHub Release from the same exact canonical root-Test bundle.
> Its top-level `.github/workflows/release-gate-mcp.yml` job owns the PyPI
> Trusted Publisher identity. Configuring this path does not itself publish a
> version; only an owner-authorized release tag does.

Replace the final publication-evidence paragraph's first sentence with:

> For publication, [TAUT-12.5]'s canonical root Test workflow builds and
> smokes the exact `taut-chat` core and `taut-mcp` wheels, creates the immutable
> MCP release bundle, and uploads it as the sole release-byte owner; the MCP
> tag gate publishes those bytes to PyPI and GitHub without rebuilding.

## 8. Invariants and Constraints

- **Core-only rename:** do not rename extension distributions, imports,
  commands, entry-point group, product wording, or tag families.
- **One byte owner:** canonical Test builds distributions once. Draft staging,
  PyPI, and final GitHub publication consume the verified bundle.
- **Top-level OIDC identity:** each PyPI action remains directly in its
  top-level gate. Shared Python may own state checks; reusable YAML may stage or
  finalize but may not own Trusted Publishing.
- **No secret fallback:** no API token or long-lived PyPI credential. Trusted
  Publishing uses job OIDC only.
- **Exact publication:** package name, version, tag, commit, filenames, and
  SHA-256 digests agree across the inner manifest, draft, PyPI, and final
  GitHub Release.
- **External-state priority:** an unexpected PyPI response, digest, file, or
  published GitHub state is fatal. A failed observability note cannot turn a
  mismatch into success.
- **Unpublished retag only:** retain exact leased recovery before either
  publication; never move or replace a consumed version.
- **No resolver fiction:** do not add a dummy `taut` distribution, metadata
  alias, `--no-deps` compatibility proof, or overlapping compatibility wheel.
- **No drive-by release redesign:** do not port SimpleBroker's tag-before/after
  CI ordering, its backend baseline policy, or unrelated release settings.
- **No new runtime dependency:** publication helpers use the standard library
  and pinned Actions. Existing packaging/runtime dependency ranges change only
  where the core distribution name requires it.
- **Warnings are errors:** new tests and release commands emit no unexpected
  warnings.

Stop and re-plan if implementation requires a second distribution build, a
reusable PyPI publisher, a second core compatibility package, manual artifact
mutation, a new runtime dependency, or changing an existing tag family.

## 9. Rollout, Rollback, and One-Way Door

### Before first publication

1. Land package metadata, specs, workflows, tests, docs, and helper behavior.
2. Enable immutable GitHub Releases.
3. Create GitHub environment `pypi` with exactly the four release-tag policies
   named in the spec.
4. Configure four PyPI pending Trusted Publishers for `taut-chat`, `taut-pg`,
   `taut-summon`, and `taut-mcp`, each naming its exact top-level workflow and
   environment `pypi`.
5. Run the repository setting check and all local/hosted gates.
6. Use a new coordinated version, expected to be 0.8.1 if no intervening
   release consumes it. Do not reuse or retag 0.8.0.
7. Publish core first or allow the coordinated tag batch to expose it first;
   do not announce the release until all four exact PyPI versions and immutable
   GitHub Releases pass verification.

Before any PyPI file exists, rollback is an ordinary revert of this change plus
removal of unused pending publishers/environment policy if the owner chooses.
Existing 0.8.0 GitHub artifacts remain valid and unchanged.

### After first publication

The project/version/file tuple on PyPI is a one-way door. Do not delete and
republish, move tags, or replace GitHub assets. Correct source or metadata with
a new patch version. A partial matching PyPI upload may be completed only from
the same verified bundle; any mismatch requires stopping and choosing a new
version after diagnosis.

Post-deploy success evidence:

- each PyPI JSON endpoint reports the exact package/version and the expected
  wheel/sdist SHA-256 digests;
- each GitHub Release is public, immutable, points at the tested commit, and
  exposes the same wheel/sdist names and bytes;
- a fresh environment can install
  `taut-chat taut-pg taut-summon taut-mcp`, run `taut --version` and
  `taut-mcp --version`, import all four packages, and inspect extension
  `Requires-Dist` entries naming `taut-chat`;
- no environment used for migration contains both distributions `taut` and
  `taut-chat`.

## 10. Dependency-Ordered Tasks

### Task 1: Promote reviewed specs

Apply section 7 to [TAUT-8.6], [TAUT-12.5], [SUM-3], and [MCP-3]. Record the
promotion baseline and run spec/index/traceability checks.

Stop if review leaves the historical-wheel boundary or publication recovery
state ambiguous.

### Task 2: Red tests for package identity and compatibility

Update metadata-consistency, command-provenance, install-hint,
release-artifact, release-helper, wheel-builder, and core/Summon matrix tests
first. Replace impossible prior-Summon install claims with explicit historical
metadata evidence and current-pair proofs.

Use real built wheels and real resolver environments. Mock only HTTP responses,
GitHub API payloads, subprocess boundaries already mocked by the release-helper
suite, and clocks/retry waits.

### Task 3: Rename core distribution metadata

Change root project name to `taut-chat`; update extension floors and uv source
keys; update diagnostic provenance and install hints; regenerate the retained
Summon and MCP locks; update package-name/tag mappings and release builders.

Run focused metadata, registry, CLI, release-artifact, and wheel-matrix tests.
Inspect built METADATA rather than relying only on TOML text.

### Task 4: Add publication-state helper

Adapt SimpleBroker's bounded GitHub draft/finalization and package/version
state machinery, then add Taut-specific PyPI JSON file/digest verification:

- exact tag/draft lookup and immutable finalization;
- expected wheel/sdist asset-set validation with a bounded wait only for
  not-yet-visible uploaded state or digest metadata;
- PyPI project/version/file/digest planning and bounded verification;
- safe complete and matching-partial reruns;
- no CLI token argument.

Do not port unrelated SimpleBroker release settings or build behavior.

### Task 5: Wire draft-first top-level publication

Revise the shared release workflow to stage the verified bundle and draft.
Add a shared least-privilege finalizer. In each top-level gate, add the direct
Trusted Publishing job with its exact package name and URL, pinned action,
environment, permissions, bundle reverification, conditional
`skip-existing: true` only for a preflight-proven matching partial release,
and post-upload digest check. `skip-existing` compares filenames only; the
preflight subset-digest and postflight full-set checks are the fail-closed
mechanism. Make final publication depend on PyPI success.

Structural tests must fire for all four top-level workflows and reject PyPI in
reusable workflows.

### Task 6: Harden local release state

Make `ReleaseState.published` mean GitHub or PyPI, fail closed on PyPI query
errors, remove dead `pypi_publish`, update summaries and `--publish`, keep
leased retag only for fresh dual-negative state, and add the bounded repository
settings check.

### Task 7: Align user and implementation documentation

Update `README.md`, all extension READMEs, `CHANGELOG.md`,
`docs/implementation/02-repository-map.md`,
`docs/implementation/04-taut-architecture.md`,
`docs/implementation/05-taut-summon-architecture.md`,
`docs/implementation/06-command-extensions.md`, and
`docs/implementation/07-taut-mcp-architecture.md`.

Use `taut-chat` only where distribution identity or install environment is
meant. Keep Taut, `taut`, and extension names everywhere else.

### Task 8: Verify and review

Run focused suites after each slice, then the normal root, PG, Summon, MCP,
workflow, packaging, lock, spec, and documentation gates. Run an independent
cross-model implementation review against the promoted spec and dispose every
finding before calling the change ready.

## 11. Testing and Verification

Red-green TDD applies to metadata, helper, workflow, and compatibility behavior.
Documentation-only wording follows inspection gates.

Required focused proof:

- root wheel/sdist metadata name `taut-chat` while importing and invoking
  `taut`;
- every extension name unchanged and every core dependency exactly
  `taut-chat>=<root-version>`;
- all four package/tag mappings and artifact prefixes;
- current core/current extensions install together from real wheels;
- historical Summon metadata records `Requires-Dist: taut` and is not passed
  off as compatible;
- GitHub or PyPI existing state blocks version reuse and retag;
- 404 means unpublished; non-404 HTTP, network, invalid JSON, name mismatch,
  version mismatch, unexpected file, extra file, and digest mismatch fail;
- absent, matching-partial, matching-complete, and post-upload PyPI states;
- missing, duplicate, draft, published mutable, published immutable, wrong
  tag, wrong SHA, missing asset, extra asset, and incomplete asset GitHub
  states;
- every PyPI job is top-level, uses `pypi`, has `id-token: write` and
  `actions: read`, lacks `contents: write`, and uses the pinned publisher;
- draft precedes PyPI, final GitHub publication follows verified PyPI, and no
  release workflow builds a distribution;
- settings checks cover immutable releases, absent/wrong environment policy,
  and the exact four tag patterns;
- package imports, command names, reserved `taut-summon` owner, MCP version
  lookup, and existing tag families remain unchanged.

Adversarial acceptance probes:

- malformed package/version/tag names;
- duplicate and traversal-like asset names;
- HTTP 401/403/429/500 and invalid JSON;
- normalized project-name variants;
- partial publication with one correct file and with one wrong digest;
- rerun after PyPI success but before GitHub finalization;
- remote tag movement between stage and finalization;
- a stale draft plus an already immutable public release;
- a workflow mutation that introduces `python -m build`, `uv build`, or an
  unpinned publish action in a tag gate.

What must stay real:

- built wheel/sdist METADATA and filenames;
- pip/uv dependency resolution in clean temporary environments;
- release bundle manifest/digest verification;
- the real `release-artifact.py create` and `verify` output accepted by the
  publication helper's strict manifest and local-file gate;
- YAML files parsed from disk;
- local git tag-planning tests where the current suite already uses real repos.

Allowed mocks:

- GitHub and PyPI HTTP endpoints;
- retry sleeps;
- subprocess calls in release-helper unit tests that already isolate commands.

Final commands are derived from the repository's current normal gates. At
minimum:

```text
uv run --extra dev pytest tests/test_project_metadata_consistency.py tests/test_command_registry.py tests/test_cli.py
uv run --extra dev pytest tests/test_release_artifact.py tests/test_release_script.py tests/test_github_workflows.py
uv run --extra dev pytest tests/test_core_summon_wheel_matrix.py
uv run --extra dev python bin/build-and-check-release-wheels.py
uv lock --project extensions/taut_summon --check
uv lock --project extensions/taut_mcp --check
bin/check-plan-status-index
```

Then run the full repository precheck sequence required by [TAUT-12.5] or the
unchanged helper's checks-only mode after the implementation is complete.

## 12. Independent Review Loop

Plan gate:

- Reviewer: Claude Opus via `claude -p`, read-only tools, because the user
  requires Opus for Claude reviews and [DOM-11] prefers another family.
- Review target: this plan and exact spec delta at baseline
  `37432deb3d876c3735a7709947809cdee554f4b6`.
- Stance: find errors, bad ideas, hidden one-way states, compatibility gaps,
  unsafe reruns, and performative overengineering. Prefer removing unnecessary
  work. The accepted product boundary is core-only rename; extension names,
  imports, commands, and tags stay fixed.
- Gate questions: is the behavior sufficiently specified to implement without
  invention, and does the plan cover the important failure/rollback edges?
- Record findings and dispositions below. Run a second pass only over accepted
  changes.

Implementation gate:

- Review the exact diff against the promotion baseline after focused and full
  verification.
- Require finding IDs, suggested dispositions, and PASS/BLOCKED. Reproduce
  factual claims before changing code.

## 13. Review Findings and Dispositions

| ID | Review finding | Disposition | Evidence |
|----|----------------|-------------|----------|
| P1 | The draft invented a root lockfile and a root `uv lock --check` gate. | Accepted. Removed all root-lock claims and kept only the retained Summon and MCP locks. | Baseline has no root `uv.lock`; `bin/release.py` owns only Summon and MCP lock paths. |
| P2 | PyPI filename/digest verification is new work, not copied from SimpleBroker. | Accepted. The task now distinguishes adapted GitHub/package-version state from Taut-specific PyPI JSON digest verification. | SimpleBroker checks PyPI name/version only. |
| P3 | Partial recovery must name `skip-existing` and state that it does not verify digests. | Accepted. The plan permits it only for a preflight-proven matching partial set and makes the surrounding digest checks load-bearing. | Upstream PyPI action documents filename-only `skip-existing` and recommends avoiding blanket use. |
| P4 | Reusable staging plus inline PyPI plus reusable finalization adds workflow surface compared with SimpleBroker's single top-level file. | Accepted as planned. Taut already centralizes exact-artifact verification in a reusable workflow; two shared non-OIDC phases avoid four large copies while the one unsupported phase remains top-level. | Current Taut has four thin gates plus shared publication; PyPI's own docs recommend keeping other work reusable while the publish job stays top-level. |
| P5 | The [TAUT-8.6] insertion anchor was descriptive rather than literal. | Accepted. Replaced it with the exact opening text of the target paragraph. | `docs/specs/02-taut-core.md` at the recorded baseline. |
| R2 | Narrow second-pass review of accepted P1-P5 changes. | Passed. No new blocker; all five dispositions were verified against the baseline. | Claude Opus round 2, 2026-07-29, read-only. |
| I1 | Publishing a draft whose explicit target SHA differs from current default-branch workflow files can require Workflows-write permission, which Actions' `GITHUB_TOKEN` cannot receive; failure after PyPI would strand a draft. | Accepted. The existing, separately verified tag remains the exact commit binding, while the GitHub Release's nominal `target_commitish` is the default branch. | GitHub's 2026-03-10 create/update-release contract says `target_commitish` is unused when the tag already exists and documents the workflow-permission constraint. Structural tests reject restoring the tag SHA as the nominal target. |
| I2 | The repository-settings parser silently accepted malformed or duplicate deployment-policy records when the required set was also present. | Accepted. Require exactly four valid, unique policy records and the exact expected set. | Added malformed, duplicate, and extra-record firing tests in `tests/test_release_script.py`. |
| I3 | `ReleaseTarget.github_release` and `github_release_enabled` were dead compatibility surfaces because every target always publishes to GitHub. | Accepted. Removed the field, property, conditional, and constructor assertions. | Release-state inspection now unconditionally queries both GitHub and PyPI for every target. |
| I4 | The strict publication reader was tested only with hand-written manifests, not with the real release-artifact producer and verifier. | Accepted. Added one production-path test that runs both CLI commands and passes their exact manifest/publish directory to `read_publication`. | `tests/test_release_artifact.py::test_cli_bundle_output_is_accepted_by_publication_gate`. |
| I5 | A release-API response may not yet expose an expected uploaded asset's digest, so the finalizer could strand an otherwise valid draft. | Accepted. The finalizer now boundedly refetches only pending expected asset metadata. Extra assets, malformed or mismatched digests, and exhaustion fail immediately or at the bound. | Focused recovery and exhaustion tests in `tests/test_release_publication.py`; the managed public-rerun path already passed this finalizer before becoming immutable. |
| I6 | The old-core resolver rejection is metadata-only until a prior `taut-chat` release exists. | Accepted as a bootstrap residual, not concealed with a fabricated alias or co-install. The live resolver case becomes required once a prior `taut-chat` baseline exists, as [TAUT-12.5] already states. | The first `taut-chat` version has no real older `taut-chat` wheel; historical `taut` wheels are a different distribution. |
| I7 | The public-GitHub/incomplete-PyPI guard is unreachable in the managed order but lacked an explanation. | Accepted. Added the ordering invariant next to the fail-closed guard. | Finalization verifies exact PyPI state before changing the draft to public. |
| I8 | Confirm the wheel-matrix deletion did not leave `core_metadata` dead. | Verified; no change required. | `core_metadata` remains consumed by `_validate_new_metadata`; the changed-file Ruff gate passes. |
| R3 | Narrow Opus second pass over I4-I8 found no blocker, but noted repository-wide refetch cost and a needless wait on immutable public state. | Passed with both non-blocking tightenings accepted. Asset retries stop as soon as the push-visible release listing finds the known id; immutable public state is checked once without waiting; the finalizer performs a single PyPI recheck because the preceding job owns the bounded wait. | Claude Opus, 2026-07-29, read-only; focused tests cover known-id recovery, exhaustion, and no-wait immutable failure. |
| I9 | The first live 0.8.1 release preflight rejected the new PyPI-only READMEs because the helper required removed legacy tag and wheel examples to exist. | Accepted. Reconciliation now updates every matching example when present and treats zero examples as a valid no-op; the spec's every-copy invariant remains unchanged. | A failing-first regression test reproduced the real preflight exit, then the full release-helper suite, focused Ruff, and mypy passed. |
| I10 | Existing package `dist/` directories could retain artifacts from earlier versions because ordinary `uv build` writes alongside existing files. | Accepted from the owner's rollout requirement. Empty and verify all four fixed directories immediately before any ordinary build; preserve the directories, fail closed on symlink/non-directory boundaries, and make dry-run non-mutating. | Failing-first real-filesystem tests cover nested stale content and dry-run preservation; an order test proves cleanup precedes the first build; the full release-helper suite passes under xdist without touching repository outputs. |
| R4 | Independent rollout review found no release blocker. It noted that dry-run skipped read-only symlink/non-directory boundary checks, the symlink firing test is branch-level for cross-platform compatibility, and absent README patterns can no longer diagnose a changed example format. | Accepted F1: dry-run now performs the same non-mutating boundary checks, with a firing test for both modes. Accepted F2 as the portable branch proof paired with real nested-file cleanup. Accepted F3 as the explicit I9 contract: zero legacy examples is valid, while the retained positive test proves present examples update. | Claude Opus, 2026-08-05, read-only PASS; local author reran the executable gates because the reviewer sandbox could not run pytest. |
| I11 | The live helper run showed root `uv build` writing to `/Users/van/dist` because the checkout was a member of an ambient parent uv workspace, while cleanup correctly emptied the repository's own root `dist/`. The first explicit-source probe corrected the output but created a forbidden root `uv.lock`. | Accepted as a release-boundary bug. Every ordinary build now names its source and matching package-local output directory explicitly and uses `--no-sources`; cleanup and build share one fixed path owner without workspace source resolution or root-lock creation. | The new command-shape test failed on bare `uv build` before implementation. Under the same parent workspace, `uv build --no-sources --out-dir dist .` reported repository-local artifacts and left no root lock. The already-pushed 0.8.1 tag was not moved; canonical CI bytes use an isolated checkout and remain independently verified. |
| R5 | Independent I11 review found no blocker. It noted the explicit output paths remain relative to the fixed `CommandStep.cwd`, and no assertion directly equated the resolved build outputs with cleanup owners. | Accepted the useful proof: the all-four command test now asserts every step's cwd is `PROJECT_ROOT` and each resolved `--out-dir` equals the corresponding `RELEASE_DIST_PATHS` entry. Retained readable relative CLI paths because their cwd owner is explicit and now test-bound. | Claude Opus, 2026-08-05, read-only PASS; local executable gates own runtime proof. |
| R6 | Narrow follow-up review examined the `--no-sources` addition after the real explicit-source probe created a root lock. | Passed. `--no-sources` disables only development workspace redirects, preserves PEP 621 dependency names and floors in artifact metadata, and is the correct publishable-build mode. Tests and docs consistently pin it on all four ordinary builds. | Claude Opus, 2026-08-05, read-only PASS; the real parent-workspace build produced repository-local wheel/sdist files and no root lock. |
| I12 | The first canonical 0.8.1 root Test run exposed three deterministic Windows failures in repository policy tests: OS-native separators were compared with Git's POSIX paths, a fixture doubled existing CRLF bytes, and another fixture used the Windows-invalid `|` filename. A focused xdist run also exposed that Ruff subprocesses could create the forbidden root `uv.lock` concurrently with the test asserting its absence. | Accepted. Normalize discovered paths with `as_posix()`, normalize fixture bytes before constructing CRLF, use a Windows-valid Markdown-unsafe backtick filename, and invoke the already-installed pinned Ruff module through the current interpreter. The manifest and retained extension-lock assertions continue to prove the dependency pin without a hidden workspace write. Because no 0.8.1 GitHub Release or PyPI file exists, recover all four staging tags with the helper's leased `--retag` path after the corrected commit passes local gates. | The same three failures reproduced on all four supported Windows Python versions (3.11-3.14). All 40 focused tests then passed under two xdist workers and left root `uv.lock` absent; serial and parallel three-test probes also passed. Root CI run `31035630991` is retained as failed evidence, not rerun into invisibility. |
| R7 | Independent I12 review found the Windows fixes sound and the named lockfile race closed. It noted that the MCP runtime-pin proof becomes a static lock proof, the current interpreter must contain the dev-extra Ruff pin, and Ruff's own cache was another repository-local write. | Accepted the cache finding: every test-owned Ruff check now uses `--no-cache`. Accepted the pin tradeoff explicitly: all manifests and retained extension locks prove the configured pin, while the current canonical pytest interpreter proves the installed pin; canonical jobs install `.[dev]` before pytest. Confirmed Git emits POSIX paths for the normalized comparison. | Claude Opus, 2026-08-05, read-only PASS; focused execution and the canonical workflow definition provide the runtime evidence. |
| I13 | The corrected dry run exposed that release prechecks still used syncing `uv run` commands. In this checkout's ambient parent workspace, those commands could recreate root `uv.lock` after the helper's clean-tree check and before its remote-action revalidation. | Accepted. All release-owned `uv run` commands now use `--no-sync`, making prechecks consumers of the already prepared release environment rather than dependency writers. The release precheck environment also sets `UV_NO_SYNC=1`, so nested uv commands inherit the boundary. The direct generator commands use the same boundary. This does not skip any test, lint, format, or type gate; a missing dependency fails the command. | A real `uv run --no-sync --extra dev` probe executed Ruff and left root `uv.lock` absent. The exact universal command-sequence test failed before its expected contract was updated, then all 136 release-helper tests passed under xdist. `bin/pytest-pg` delegates to an inner uv command, and the inherited environment now prevents that nested sync during release prechecks. |
| R8 | Independent I13 review passed the command ordering and fail-closed dependency boundary. It identified the nested uv call behind `bin/pytest-pg`, the prepared-environment prerequisite, and wording that could overstate MCP's runtime pin proof. | Accepted nested protection by setting `UV_NO_SYNC=1` on every precheck process; retained standalone `bin/pytest-pg` syncing outside the release boundary. Accepted the prepared dev environment as an explicit release prerequisite: missing tools fail rather than changing the graph during release. Clarified that MCP's proof is its retained static lock, while the canonical root interpreter supplies the runtime Ruff proof. | Claude Opus, 2026-08-05, read-only PASS; environment-override firing assertions cover live and local-LLM command branches. |

## 14. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TAUT-6.4], [SUM-3] | Keep the pre-existing temporary bridge while changing its install hint. | Removed the legacy CLI-delegation branch; the reserved core fallback now emits only the `taut-summon` install hint. | Historical Summon wheels require distribution `taut` and cannot resolve with `taut-chat`. The delegation branch therefore had no supported caller after the rename, and repository policy forbids retaining dead code. | Promoted directly in [TAUT-6.4] and [SUM-3]; implementation guidance and firing tests were aligned in the same slice. |

## 15. Out of Scope

- Claiming, transferring, or renaming the prohibited PyPI project `taut`.
- Renaming any extension distribution to `taut-chat-*`.
- Changing import packages, console commands, entry-point group, MCP tool
  behavior, databases, or Taut product branding.
- Publishing a compatibility distribution named `taut`.
- Rewriting or republishing 0.8.0 artifacts.
- Changing release-tag families or adopting SimpleBroker's write-once tag
  timing. Taut keeps leased recovery for unpublished failures.
- Moving canonical release builds out of root Test.
- Adding a package-runtime dependency for release support.
- Performing the real release or mutating PyPI/GitHub repository settings
  without separate owner authorization.

## 16. Fresh-Eyes Completion Review

Before completion, inspect the final diff from the perspective of a user who
types `pipx install taut-chat` and an operator recovering a half-complete
release:

1. Can any documented command accidentally ask for `taut-chat-summon`,
   `taut-chat-mcp`, or another renamed extension?
2. Can any old `Requires-Dist: taut` claim survive in a current artifact or
   compatibility assertion?
3. Can PyPI see bytes that were not built and verified by canonical Test?
4. Can a rerun overwrite, conceal, or accept a mismatched external file?
5. Can a public GitHub Release appear before PyPI is exact and complete?
6. Can `--retag` move a version after either publication destination exists?
7. Do the specs, implementation notes, READMEs, changelog, and tests all
   distinguish product/import name from distribution name?

Completion requires concrete changed-file evidence, observed verification
results, independent review disposition, and either a user-authorized commit or
an explicit report that the reviewed work remains uncommitted.

## 17. Verification Evidence

Observed locally on 2026-07-29:

- `uv run --extra dev pytest -q -n auto`: passed with one expected
  Windows-only filename-contract skip.
- Release/publication focus, including the real bundle-producer/consumer
  contract: all selected tests passed.
- Root and PG fast suites: 214 PG-marked root tests and all 14 extension PG
  tests passed in the earlier full implementation gate.
- Full Summon and MCP suites: both exited 0 with their required 100% coverage
  gates in the earlier full implementation gate.
- `uv run bin/build-and-check-release-wheels.py`: built and installed the real
  `taut_chat-0.8.0` and `taut_summon-0.8.0` wheels, passed core-only and
  current-pair live controls, and confirmed historical Summon 0.5.4 records
  `Requires-Dist: taut>=0.5.4` only as incompatible historical metadata.
- Changed-file Ruff check/format and targeted mypy: passed.
- `uv run bin/check-doc-paths`: 820 claims passed.
- `uv run bin/check-cli-claims`: 199 claims passed.
- Summon and MCP `uv lock --check`, plan-index validation, and
  `git diff --check`: passed.

The repository-wide Ruff formatter also reports old code-block formatting in
three untouched historical plan files. This change does not rewrite those
records; every changed Python and Markdown file passes the formatter. Hosted
OIDC publication, immutable-release transition, and live GitHub asset-digest
evidence remain rollout gates. The work remains uncommitted until the user
requests a commit.

Rollout follow-up on 2026-08-05: the first real 0.8.1 invocation stopped before
mutation because the helper still required legacy versioned README examples
removed by this plan's PyPI-first documentation. The no-example regression
test failed at that exact guard before the correction. The owner then required
all package `dist/` directories to be empty before release builds; its direct
filesystem and build-order tests also failed before implementation. After both
corrections, the full release-helper suite, focused Ruff format/check, targeted
mypy, and `git diff --check` passed. Hosted OIDC publication and exact
both-destination digest proof remain the final rollout gates.

The first canonical 0.8.1 root Test run subsequently failed on deterministic
Windows-only assumptions in three repository policy tests. The same run also
made visible a hidden write/race in those tests: Ruff was launched through
`uv run`, which could create the root lock while another xdist worker asserted
that the lock was absent. The portable, non-mutating focused suite passed in
both serial and two-worker modes. Since publication had not begun, the four
0.8.1 staging tags are eligible for the release helper's leased retag recovery;
the failed run remains permanent evidence and the replacement commit must pass
fresh canonical workflows before any publication gate can succeed.

The independent review also identified Ruff's default repository cache as a
second unnecessary test write. The policy tests now disable that cache. The
root and MCP manifest/lock checks remain the configured-pin proof; the Ruff
module installed into the canonical dev-extra test interpreter is the runtime
pin proof.
