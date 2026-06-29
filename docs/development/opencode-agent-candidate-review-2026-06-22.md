# OpenCode Agent Candidate Review - 2026-06-22

This note records the live review of four external repositories considered for
OpenCode Agents and Strix. The conclusion is intentionally conservative: import
review contracts, not whole toolchains, unless the tool solves a concrete
failure that the current workflow cannot solve.

## Decision table

| Candidate | Live state checked | Decision | OpenCode action | Strix action |
| --- | --- | --- | --- | --- |
| `epoko77-ai/im-not-ai` | Public, non-fork, MIT, Python, default `main`, pushed 2026-06-09, updated 2026-06-22 | Adapt | Keep only the Korean prose constraint: preserve facts, identifiers, numbers, and quotes; remove only formulaic filler or translationese. Do not install its humanizer pipeline in CI. | Not applicable. Style-only guidance must not affect security findings. |
| `DietrichGebert/ponytail` | Public, non-fork, MIT, JavaScript, default `main`, pushed 2026-06-21, updated 2026-06-22 | Adapt | Keep the minimal-change rule: prefer deletion, stdlib/native platform features, and already-installed dependencies before new code or packages. Preserve validation, data-loss handling, security, accessibility, and required tests. | Indirect only. Strix must not turn minimalism into skipped security work. |
| `tirth8205/code-review-graph` | Public, non-fork, MIT, Python, default `main`, pushed 2026-06-14, updated 2026-06-22 | Reference only | Do not install another graph stack. Current OpenCode review already initializes CodeGraph and requires CodeGraph MCP for structural review before broad local reads. | No direct Strix import. Structural context remains an OpenCode review input, not a Strix model replacement. |
| `cdppcorp/KKTV` | Public, non-fork, MIT, Python, default `main`, pushed 2026-03-27, updated 2026-06-13 | Adapt | Use its KISA/CWE taxonomy only when failed-check or Strix evidence supports the class. Do not copy the 47-rule skill pipeline or generated manuscript material. | Yes, as evidence-backed category language: injection, auth/authz, secrets, crypto, traversal/upload, XSS/CSRF/SSRF, error disclosure, debug/deployment config. |

## Current workflow contracts

The current OpenCode workflow already carries the useful candidate-derived
contracts:

- CodeGraph is initialized before review and the prompt requires CodeGraph MCP
  for blast-radius, call graph, and test-coverage questions before broad local
  reads.
- OpenCode tries a three-model ladder and sets `OPENCODE_MODEL_ATTEMPTS: "2"` on
  each model path, so transient model execution failures get a retry before the
  workflow moves on.
- If all model outputs fail, the approval step stays fail-closed for source,
  workflow, script, dependency, infrastructure, config, and lockfile changes.
- Documentation, policy, and non-executable metadata can use the deterministic
  low-risk fallback only after same-head peer checks, review threads, and
  mergeability are verified.
- Failed-check diagnosis must inspect logs and local source lines. A failed
  check URL, workflow name, or generic failure summary is not enough.
- Strix multi-model evidence is not collapsed: one Strix model vulnerability
  report requires one distinct OpenCode finding.

## Evidence from `.github` PR #2

The referenced review
`https://github.com/ContextualWisdomLab/.github/pull/2#pullrequestreview-4537191848`
was a real all-model-failure case:

- Review `4537191848` requested changes with
  `primary=failure, fallback=failure, second_fallback=failure`.
- The same PR later produced same-head retry reviews, then a deterministic
  low-risk approval for a `SECURITY.md`-only change at head
  `b05216a1425d6d13c8a85aee2ed8d21fa3c5cc52`.
- PR #2 was merged on 2026-06-22 after the low-risk fallback approval and green
  OpenCode checks.

That pattern is the intended behavior: do not approve invalid review output for
source-bearing changes, but do not permanently block metadata-only changes when
current-head checks, human review threads, and mergeability are clean.

## Non-import rationale

The rejected part is the toolchain, not the useful ideas:

- `im-not-ai` contains installer scripts and multi-agent humanizing behavior
  meant for prose rewriting. Running that in CI would add style churn and could
  mutate factual/security language.
- `ponytail` includes plugins, hooks, benchmarks, and commands. OpenCode only
  needs the minimal-change rule, not another runtime plugin.
- `code-review-graph` overlaps with the existing CodeGraph MCP path. Installing
  both would create two graph sources with different indexes and failure modes.
- `KKTV` contains large guide/manuscript/reference material. OpenCode and Strix
  need evidence-backed categories, not a second security scanner pipeline.

## Verification hooks

The durable OpenCode and Strix contracts now live in the central required
workflows in `ContextualWisdomLab/.github`, not in repo-local Naruon shell
scripts. Naruon should be used as live evidence that the organization workflow
handles the cases this review identified:

- CodeGraph initialization and CodeGraph MCP prompt usage.
- Candidate-derived prompt constraints for CodeGraph, Ponytail, im-not-ai, and
  KKTV.
- Multiple model attempts and per-model retry logging.
- Failed-check evidence collection for current-head Strix workflow runs.
- Deterministic low-risk fallback limits and fail-closed invalid-output
  behavior.
- Outdated branch updates through the target repository's
  `github-actions[bot]` when the PR is otherwise mergeable.
