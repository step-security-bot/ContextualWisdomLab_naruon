# Merge Gate Policy

This repository's merge gate is evidence-based: required checks must pass,
review threads must be resolved, and the current PR head must have current-head
CodeRabbit/robot-review evidence. Human review is not awaited by default.

## Required gate contract

- Required status checks must pass on the current head SHA.
- Application CI must run backend pytest and frontend test/lint/build checks on
  pull requests to `master` and `release/**`, while release-branch pushes must
  not create duplicate check noise; push checks are scoped to `master`.
- The CodeRabbit robot-review gate is satisfied by current-head CodeRabbit
  evidence only when current-head blocking findings, warnings, and failures are
  fixed, rebutted with evidence, or superseded. Authoritative current-head
  `Review skipped` evidence satisfies the robot-review gate when applicable.
- PR Governance automation is metadata-only: it must not checkout pull request
  code, clone the head branch, dismiss reviews, enable auto-merge, or use admin
  merge. It may read PR/check/review-thread metadata and post blocker comments;
  the separate human/agent landing path performs any allowed merge action after
  current-head gates are satisfied.
- PR Governance runs trusted-base logic only. The workflow materializes the base
  repository script from a trusted tarball and must not execute PR-head scripts.
  Trusted tarball materialization uses bounded retry plus archive validation for
  transient GitHub API truncation and fails closed instead of falling back to
  PR-head or local scripts.
- Pending, queued, requested, waiting, or in-progress checks are wait states, not
  hard failure findings. Failed, cancelled, timed-out, and action-required states
  are blockers.
- `reviewDecision=CHANGES_REQUESTED` is a blocker until requested changes are
  addressed or superseded on the current head.
- Blocker comments use the idempotent
  `<!-- pr-governance:metadata-gate -->` marker and are patched in place instead
  of duplicated on repeated workflow events.
- GitHub rulesets must use `required_approving_review_count=0` so GitHub does
  not require a human `APPROVED` review when robot-review policy applies.
- GitHub rulesets must keep `required_review_thread_resolution=true`.
- CodeRabbit `request_changes_workflow` stays enabled so the robot can clear
  its own requested-changes review after comments are resolved. CodeRabbit
  GitHub Checks integration stays disabled because GitHub Actions are already
  evaluated by required checks and PR Governance; duplicating that gate inside
  CodeRabbit can strand stale GitHub `CHANGES_REQUESTED` review objects when an
  unrelated scanner is temporarily failing.
- Bypass actors must not be configured for routine delivery.
- Security workflows and scanners are required gates, not optional paths.
- Required OpenCode Review, Strix Security Scan, and PR Review Merge Scheduler
  are supplied by the organization required workflow ruleset from
  `ContextualWisdomLab/.github`. This repository must not carry repo-local `.github/workflows/opencode-review.yml`, repo-local `.github/workflows/strix.yml`, repo-local `.github/workflows/pr-review-merge-scheduler.yml`, or repo-local Strix quick-gate scripts and OpenCode helper scripts.
- OpenCode observes and reviews current-head evidence before it approves,
  requests changes, or publishes retry guidance. Failed GitHub Checks are explained by the central OpenCode workflow with the failed check name, log or
  annotation evidence, source path/line when available, fix direction, and a
  rerun or verification command.
- Strix Security Scan is supplied by the organization required workflow and is
  not configured from this repository's workflow files or CI helper scripts.
- Mechanical branch update, auto-merge, and merge actions run as the target
  repository's `github-actions[bot]` through the central workflow. If GitHub
  reports the PR branch is behind or outdated and merge is otherwise waitable,
  the scheduler should update the branch from the target branch before waiting
  for checks again. If the update is blocked by conflicts, the review or gate
  output must name the base/head branch pair, describe that the author must merge
  or rebase the target branch into the PR branch, resolve conflict markers, and
  rerun focused checks.

## Evidence commands

Use the same head SHA across all checks:

```bash
gh pr view <pr> \
  --json number,headRefOid,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup
gh pr checks <pr> --required
gh api repos/<owner>/<repo>/pulls/<pr>/reviews
gh api repos/<owner>/<repo>/commits/<sha>/check-runs
gh api repos/<owner>/<repo>/rulesets --jq '.[] | {name, enforcement, rules}'
```

## Robot review versus GitHub approval

CodeRabbit review/check evidence satisfies this repo's robot-review policy only
after current-head CodeRabbit blocking comments, pre-merge warnings, and failure
findings are resolved or superseded. It is not the same object as a GitHub
`APPROVED` review. If GitHub reports a missing approving review, inspect the
ruleset before waiting for a human review. The expected setting is
`required_approving_review_count=0`.

## Stale required contexts

A required context can become stale when the PR is fixing the workflow that
emits it. For example, PRs that fix Strix may be blocked by a required `strix`
context before the hardened Strix workflow can emit a valid result.

Handling policy:

1. Prefer branch update or rerun first.
2. If the required context cannot be emitted until the PR lands, document the
   stale context and use only a temporary, reversible ruleset adjustment.
   Capture equivalent temporary evidence before merge, such as a trusted-base
   rerun, scanner artifact, SARIF output, or manual security review evidence
   tied to the current head SHA.
3. Restore the `strix` required context after the hardened workflow emits it
   successfully on the protected branch.
4. Re-run required-check evidence after restore.

## PR #108/#109 evidence summary

- PR #108 exposed the merge-gate ambiguity: CodeRabbit/robot-review evidence was
  conflated with a GitHub `APPROVED` review, while ruleset configuration could
  still require human approval despite repo policy.
- Issue #109 documents the durable fix: distinguish robot-review evidence from
  GitHub approval objects, keep human approval count at zero, preserve review
  thread resolution, and handle stale `strix` required contexts with explicit
  rollback.
- The root cause was policy/evidence mismatch, not lack of human review.

## Rollback and recovery

- Do not add bypass actors, disable security checks, dismiss reviews, or use admin
  merge for normal delivery.
- Any temporary ruleset change must have captured before/after JSON, owner,
  expiry, head SHA, equivalent temporary evidence, and a named restore
  condition.
- Restore required contexts immediately after the repaired workflow emits them.
- If the platform still rejects merge after policy-aligned settings and passing
  checks, record the rejection as an external blocker with the exact command
  output and head SHA.

## Related operations docs

- `docs/operations/release-deployment-architecture.md`
- `docs/operations/open-source-apm.md`
- `docs/operations/email-relay-proxy-boundary.md`
- `docs/operations/postgresql-physical-replication.md`
- `docs/operations/auth-key-management.md`
- `docs/operations/traefik-evaluation.md`
