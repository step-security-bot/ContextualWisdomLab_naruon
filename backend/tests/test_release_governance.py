"""Regression tests for release governance artifacts.

These tests intentionally exercise repository-level release contracts from the
backend test suite so CI catches drift in versioning, changelog, and GitHub
workflow governance before a release branch can land.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import importlib.util
import shutil
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
OCI_PREDEFINED_IMAGE_ANNOTATION_KEYS = {
    "org.opencontainers.image.created",
    "org.opencontainers.image.authors",
    "org.opencontainers.image.url",
    "org.opencontainers.image.documentation",
    "org.opencontainers.image.source",
    "org.opencontainers.image.version",
    "org.opencontainers.image.revision",
    "org.opencontainers.image.vendor",
    "org.opencontainers.image.licenses",
    "org.opencontainers.image.ref.name",
    "org.opencontainers.image.title",
    "org.opencontainers.image.description",
    "org.opencontainers.image.base.digest",
    "org.opencontainers.image.base.name",
}


def read_repo_text(relative_path: str) -> str:
    """Read a repository file with a clear assertion when it is missing."""
    path = REPO_ROOT / relative_path
    assert path.exists(), f"required governance artifact is missing: {relative_path}"
    return path.read_text(encoding="utf-8")


def assert_dockerfile_stage_from(dockerfile: str, image: str, stage_alias: str) -> None:
    pattern = (
        rf"^FROM {re.escape(image)}@sha256:[0-9a-f]{{64}} AS {re.escape(stage_alias)}$"
    )
    assert re.search(pattern, dockerfile, flags=re.MULTILINE), (
        f"missing pinned {image} stage alias {stage_alias}"
    )


def test_root_version_exists_and_is_initial_semver_release() -> None:
    version = read_repo_text("VERSION").strip()

    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"VERSION is not valid SemVer: {version!r}"
    )


def test_release_version_sources_are_synchronized() -> None:
    version = read_repo_text("VERSION").strip()
    frontend_package = json.loads(read_repo_text("frontend/package.json"))
    backend_main = read_repo_text("backend/main.py")
    runtime_config = read_repo_text("backend/api/runtime_config.py")
    dockerfile = read_repo_text("Dockerfile")

    assert frontend_package["version"] == version
    assert "version=get_release_version()" in backend_main
    assert "version=get_release_version()" in runtime_config
    assert "COPY VERSION /app/VERSION" in dockerfile
    assert 'ARG OCI_IMAGE_TITLE="naruon"' in dockerfile
    assert 'org.opencontainers.image.title="${OCI_IMAGE_TITLE}"' in dockerfile
    assert 'ARG OCI_IMAGE_SOURCE="https://github.com/Seongho-Bae/naruon"' in dockerfile
    assert 'org.opencontainers.image.source="${OCI_IMAGE_SOURCE}"' in dockerfile


def test_container_images_cover_all_oci_predefined_image_annotations() -> None:
    root_dockerfile = read_repo_text("Dockerfile")
    frontend_dockerfile = read_repo_text("frontend/Dockerfile")
    docker_publish_workflow = read_repo_text(".github/workflows/docker-publish.yml")

    for annotation_key in OCI_PREDEFINED_IMAGE_ANNOTATION_KEYS:
        assert annotation_key in root_dockerfile
        assert annotation_key in frontend_dockerfile
        assert annotation_key in docker_publish_workflow

    assert (
        "DOCKER_METADATA_ANNOTATIONS_LEVELS: manifest,index" in docker_publish_workflow
    )
    assert (
        "annotations: ${{ steps.meta.outputs.annotations }}" in docker_publish_workflow
    )


def test_container_images_use_pinned_node_runtimes() -> None:
    root_dockerfile = read_repo_text("Dockerfile")
    frontend_dockerfile = read_repo_text("frontend/Dockerfile")
    docker_publish_workflow = read_repo_text(".github/workflows/docker-publish.yml")
    render_deployment = read_repo_text("docs/operations/render-deployment.md")

    assert_dockerfile_stage_from(root_dockerfile, "node:26-slim", "frontend-builder")
    assert "FROM node:26-slim@sha256:" in frontend_dockerfile
    assert "docker.io/library/node:26-slim" in frontend_dockerfile
    assert "docker.io/library/node:26-slim" in docker_publish_workflow
    assert "Node 26 toolchain" in render_deployment
    assert "node:24" not in root_dockerfile
    assert "node:24" not in frontend_dockerfile
    assert "node:24" not in docker_publish_workflow
    assert "Node 24" not in render_deployment
    assert "node:22" not in root_dockerfile
    assert "node:22" not in frontend_dockerfile
    assert "node:22" not in docker_publish_workflow
    assert "Node 22" not in render_deployment


def test_backend_images_use_python_314_runtime() -> None:
    root_dockerfile = read_repo_text("Dockerfile")
    docker_publish_workflow = read_repo_text(".github/workflows/docker-publish.yml")
    app_ci_workflow = read_repo_text(".github/workflows/app-ci.yml")
    bandit_workflow = read_repo_text(".github/workflows/bandit.yml")
    strix_workflow = read_repo_text(".github/workflows/strix.yml")
    render_deployment = read_repo_text("docs/operations/render-deployment.md")

    assert_dockerfile_stage_from(root_dockerfile, "python:3.14-slim", "backend-runtime")
    assert "docker.io/library/python:3.14-slim" in root_dockerfile
    assert "docker.io/library/python:3.14-slim" in docker_publish_workflow
    assert 'python-version: ["3.14"]' in app_ci_workflow
    assert 'python-version: "3.14"' in bandit_workflow
    assert 'python-version: "3.13"' in strix_workflow
    assert "Python 3.14 toolchain" in render_deployment
    assert "python:3.11" not in root_dockerfile
    assert "python:3.11" not in docker_publish_workflow
    assert '"3.11"' not in app_ci_workflow
    assert '"3.12"' not in app_ci_workflow
    assert 'python-version: "3.12"' not in bandit_workflow


def test_python_314_backend_image_uses_binary_wheel_dependencies() -> None:
    dockerfile = read_repo_text("Dockerfile")
    requirements = read_repo_text("backend/requirements.txt")

    assert "PIP_ONLY_BINARY=:all:" in dockerfile
    assert "asyncpg==0.31.0" in requirements
    assert "tiktoken==0.13.0" in requirements
    assert "build-essential" not in dockerfile
    assert "cargo" not in dockerfile
    assert "libpq-dev" not in dockerfile
    assert (
        "COPY backend/requirements-hashes.txt /app/requirements-hashes.txt"
        in dockerfile
    )
    assert (
        "pip install --no-cache-dir --require-hashes -r requirements-hashes.txt"
        in dockerfile
    )


def test_backend_runtime_toolchain_uses_image_scan_clean_security_pins() -> None:
    requirements = read_repo_text("backend/requirements.txt")

    assert "sqlalchemy==2.0.51" in requirements
    assert "asyncpg==0.31.0" in requirements
    assert "tiktoken==0.13.0" in requirements
    assert "protobuf==6.33.6" in requirements
    assert "setuptools==82.0.1" in requirements
    assert "wheel==0.47.0" in requirements
    assert "opentelemetry-api==1.42.1" in requirements
    assert "opentelemetry-instrumentation-fastapi==0.63b1" in requirements


def test_strix_ci_requirements_use_security_quality_clean_pins() -> None:
    strix_ci_requirements = read_repo_text("requirements-strix-ci.txt")

    assert "strix-agent==1.0.4" in strix_ci_requirements
    assert "cryptography==49.0.0" in strix_ci_requirements
    assert "python-multipart==0.0.32" in strix_ci_requirements


def test_changelog_follows_keep_a_changelog_for_initial_korean_release() -> None:
    changelog = read_repo_text("CHANGELOG.md")

    assert "Keep a Changelog" in changelog
    assert "https://keepachangelog.com/en/1.0.0/" in changelog
    assert "## [0.1.0] - 2026-05-09" in changelog
    assert "[0.0.0.1]" not in changelog
    assert "@seonghobae" in changelog
    assert "Seongho Bae (@seonghobae)" in changelog


def test_github_actions_are_pinned_to_exact_sha() -> None:
    assert WORKFLOW_DIR.exists(), (
        "required governance artifact is missing: .github/workflows"
    )
    governed_workflows = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(
        WORKFLOW_DIR.glob("*.yaml")
    )
    assert governed_workflows, "no governed GitHub workflows found"

    unpinned_major_refs: list[str] = []
    missing_version_comments: list[str] = []
    major_only_action = re.compile(
        r"uses:\s*['\"]?([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@v\d+['\"]?\s*$"
    )
    sha_without_version_comment = re.compile(
        r"uses:\s*['\"]?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}['\"]?\s*$"
    )
    for workflow_path in governed_workflows:
        workflow_lines = workflow_path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(workflow_lines, 1):
            if major_only_action.search(line):
                unpinned_major_refs.append(
                    f"{workflow_path.relative_to(REPO_ROOT)}:{line_number}:{line.strip()}"
                )
            elif sha_without_version_comment.search(line):
                missing_version_comments.append(
                    f"{workflow_path.relative_to(REPO_ROOT)}:{line_number}:{line.strip()}"
                )

    assert unpinned_major_refs == [], "\n".join(unpinned_major_refs)
    assert missing_version_comments == [], "\n".join(missing_version_comments)


def test_github_actions_unpinned_major_refs_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    workflow_dir = repo_root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    workflow_file = workflow_dir / "bad-action.yml"
    workflow_file.write_text(
        "\n".join(
            [
                "name: bad action refs",
                "jobs:",
                "  test:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
            ]
        ),
        encoding="utf-8",
    )

    this_module = sys.modules[__name__]
    monkeypatch.setattr(this_module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(this_module, "WORKFLOW_DIR", workflow_dir)

    with pytest.raises(AssertionError) as exc_info:
        test_github_actions_are_pinned_to_exact_sha()

    message = str(exc_info.value)
    assert ".github/workflows/bad-action.yml:6:- uses: actions/checkout@v4" in message

    workflow_file.write_text(
        "\n".join(
            [
                "name: missing version comment",
                "jobs:",
                "  test:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/setup-python@abcdef1234567890abcdef1234567890abcdef12",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(AssertionError) as exc_info:
        test_github_actions_are_pinned_to_exact_sha()

    message = str(exc_info.value)
    assert (
        ".github/workflows/bad-action.yml:6:- uses: "
        "actions/setup-python@abcdef1234567890abcdef1234567890abcdef12"
    ) in message


def test_bandit_security_scan_does_not_continue_on_error() -> None:
    workflow = read_repo_text(".github/workflows/bandit.yml")

    assert "continue-on-error: true" not in workflow


def test_codeql_workflow_can_read_security_events_without_uploading_sarif() -> None:
    workflow = read_repo_text(".github/workflows/codeql.yml")

    assert "permissions:\n  contents: read\n  security-events: read" in workflow
    assert (
        "    permissions:\n      actions: read\n      contents: read\n      security-events: read"
        in workflow
    )
    assert "upload: never" in workflow
    assert "security-events: write" not in workflow


def test_required_code_scanning_workflows_upload_scorecard_and_trivy_sarif() -> None:
    scorecard_workflow = read_repo_text(".github/workflows/scorecard.yml")
    trivy_workflow = read_repo_text(".github/workflows/trivy.yml")

    for workflow in (scorecard_workflow, trivy_workflow):
        assert "pull_request:" in workflow
        assert "push:" in workflow
        assert "- develop" in workflow
        assert "- master" in workflow
        assert (
            "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0"
            in workflow
        )
        assert "security-events: write" in workflow
        assert "continue-on-error: true" not in workflow
        assert (
            "github/codeql-action/upload-sarif@8aad20d150bbac5944a9f9d289da16a4b0d87c1e # v4"
            in workflow
        )

    assert (
        "ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a # v2.4.3"
        in scorecard_workflow
    )
    assert "permissions:\n  contents: read\n\njobs:" in scorecard_workflow
    assert "permissions:\n  contents: read\n\njobs:" in trivy_workflow
    assert (
        "    permissions:\n      actions: read\n      contents: read\n      id-token: write\n      security-events: write"
        in scorecard_workflow
    )
    assert (
        "    permissions:\n      contents: read\n      security-events: write"
        in trivy_workflow
    )
    assert "results_format: sarif" in scorecard_workflow
    assert "Restore Scorecard SARIF ownership" in scorecard_workflow
    assert (
        'sudo chown "$(id -u):$(id -g)" scorecard-results.sarif' in scorecard_workflow
    )
    assert "chmod u+rw scorecard-results.sarif" in scorecard_workflow
    assert "Preserve Scorecard SARIF categories" in scorecard_workflow
    assert (
        "python scripts/ci/ensure_scorecard_sarif_categories.py scorecard-results.sarif"
        in scorecard_workflow
    )
    assert "category: scorecard" in scorecard_workflow
    assert (
        "ref: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.sha || github.sha }}"
        in scorecard_workflow
    )
    assert (
        "ref: ${{ github.event_name == 'pull_request' && format('refs/pull/{0}/head', github.event.pull_request.number) || github.ref }}"
        in scorecard_workflow
    )
    assert (
        "sha: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.sha || github.sha }}"
        in scorecard_workflow
    )

    assert (
        "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25 # v0.36.0"
        in trivy_workflow
    )
    assert "format: sarif" in trivy_workflow
    assert "category: trivy" in trivy_workflow
    assert (
        "ref: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.sha || github.sha }}"
        in trivy_workflow
    )
    assert (
        "ref: ${{ github.event_name == 'pull_request' && format('refs/pull/{0}/head', github.event.pull_request.number) || github.ref }}"
        in trivy_workflow
    )
    assert (
        "sha: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.sha || github.sha }}"
        in trivy_workflow
    )


def test_scorecard_sarif_normalizer_preserves_branch_protection_category(
    tmp_path: Path,
) -> None:
    sarif_path = tmp_path / "scorecard-results.sarif"
    sarif_path.write_text(
        json.dumps(
            {
                "version": "2.1.0",
                "runs": [
                    {
                        "tool": {"driver": {"name": "Scorecard", "rules": []}},
                        "automationDetails": {"id": "supply-chain/local"},
                        "results": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    normalizer = REPO_ROOT / "scripts/ci/ensure_scorecard_sarif_categories.py"
    spec = importlib.util.spec_from_file_location("ensure_scorecard", normalizer)
    assert spec and spec.loader, "Failed to load module"
    ensure_scorecard_module = importlib.util.module_from_spec(spec)
    sys.modules["ensure_scorecard"] = ensure_scorecard_module
    spec.loader.exec_module(ensure_scorecard_module)

    sarif_path.chmod(0o444)
    try:
        for _ in range(2):
            ret = ensure_scorecard_module.main([str(normalizer), str(sarif_path)])
            assert ret == 0, f"Scorecard script failed with {ret}"
    finally:
        sarif_path.chmod(0o644)

    normalized = json.loads(sarif_path.read_text(encoding="utf-8"))
    categories = [
        run.get("automationDetails", {}).get("id") for run in normalized["runs"]
    ]
    assert categories.count("supply-chain/branch-protection") == 1
    branch_protection_run = next(
        run
        for run in normalized["runs"]
        if run.get("automationDetails", {}).get("id")
        == "supply-chain/branch-protection"
    )
    assert branch_protection_run["tool"]["driver"]["name"] == "Scorecard"
    assert branch_protection_run["results"] == []


def test_opencode_review_prompt_requires_active_mcp_evidence_use() -> None:
    workflow = read_repo_text(".github/workflows/opencode-review.yml")

    assert "Actively consult the configured MCP evidence sources" in workflow
    assert "actively consult CodeGraph MCP" in workflow
    assert "DeepWiki for repo docs" in workflow
    assert "Context7 for current library/API docs" in workflow
    assert "web_search for bounded external lookups" in workflow
    assert "If a configured MCP source is unavailable or not applicable" in workflow
    assert "Lead with findings ordered by severity" in workflow
    assert (
        "Distinguish blocking findings from important suggestions and nits" in workflow
    )
    assert "request changes only for actionable blockers" in workflow.lower()
    assert "regression test direction" in workflow
    assert "OpenCode-owned review structure compatible with Copilot Review" in workflow
    assert "CodeRabbitAI's severity-ordered, actionable finding format" in workflow
    assert (
        "Do not depend on Copilot Review, CodeRabbitAI, or any human reviewer"
        in workflow
    )
    assert "## Pull request overview" in workflow
    assert "## Findings" in workflow
    assert "No blocking findings." in workflow
    assert "Keep raw tool logs out of the main review body" in workflow
    assert (
        "<summary>Failed check evidence for line-specific fixes</summary>" in workflow
    )
    assert '"codegraph"' in workflow
    assert '"deepwiki"' in workflow
    assert '"context7"' in workflow
    assert '"web_search"' in workflow


def test_opencode_billing_lock_failed_checks_publish_neutral_comment(
    tmp_path: Path,
) -> None:
    workflow = read_repo_text(".github/workflows/opencode-review.yml")
    repo_root = tmp_path / "repo"
    workflow_file = repo_root / ".github" / "workflows" / "opencode-review.yml"
    workflow_file.parent.mkdir(parents=True)
    workflow_file.write_text(
        "If every active failed-check block says the job was not started because "
        "the GitHub account is locked due to a billing issue, classify it as an "
        "external CI/account blocker with no repository source fix.\n",
        encoding="utf-8",
    )

    assert "is_github_billing_lock_evidence()" in workflow
    assert "build_billing_lock_body()" in workflow
    assert 'create_pull_review "COMMENT"' in workflow
    assert "No source-code findings." in workflow
    assert "do not invent source-backed REQUEST_CHANGES findings for it" in workflow

    evidence_file = tmp_path / "failed-check-evidence.md"
    evidence_file.write_text(
        """
# Failed GitHub Check Evidence

## Failed check: App CI / backend

### Check annotations

- unknown:0-0 [failure] The job was not started because your account is locked due to a billing issue.

## Failed check: Strix Security Scan/strix

### Check annotations

- unknown:0-0 [failure] The job was not started because your account is locked due to a billing issue.
""".strip()
        + "\n",
        encoding="utf-8",
    )

    fallback = subprocess.run(  # nosec B603
        [
            shutil.which("bash"),
            str(
                REPO_ROOT / "scripts/ci/emit_opencode_failed_check_fallback_findings.sh"
            ),
            str(evidence_file),
            str(repo_root),
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    assert (
        "GitHub Actions billing lock blocked current-head check evidence"
        in fallback.stdout
    )
    assert "external CI/account blocker" in fallback.stdout
    assert "do not request repository source changes" in fallback.stdout
    assert "No deterministic missing-string markers" not in fallback.stdout


def test_app_ci_runs_backend_and_frontend_checks_without_duplicate_release_pushes() -> (
    None
):
    workflow = read_repo_text(".github/workflows/app-ci.yml")

    assert "pull_request:" in workflow
    assert "release/**" in workflow
    assert "python -m pytest" in workflow
    assert "PYTHONWARNINGS: error" in workflow
    assert 'DISABLE_BACKGROUND_WORKERS: "1"' in workflow
    assert "npm test" in workflow
    assert "npm run lint" in workflow
    assert "npm run build" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "concurrency:" in workflow
    assert "${{ github.event.pull_request.number || github.ref }}" in workflow
    assert "uses: actions/checkout@v" not in workflow
    assert "uses: actions/setup-python@v" not in workflow
    assert "uses: actions/setup-node@v" not in workflow

    push_block = workflow.split("push:", 1)[1].split("pull_request:", 1)[0]
    assert "master" in push_block
    assert "release/**" not in push_block


def test_pr_review_merge_scheduler_uses_minimal_token_permissions() -> None:
    workflow = read_repo_text(".github/workflows/pr-review-merge-scheduler.yml")

    assert (
        "permissions:\n"
        "      actions: read\n"
        "      checks: read\n"
        "      contents: read\n"
        "      pull-requests: write" in workflow
    )
    assert "actions: write" not in workflow
    assert "contents: write" not in workflow


def test_docker_publish_validates_pr_images_and_publishes_semver_images_only_on_tags() -> (
    None
):
    workflow = read_repo_text(".github/workflows/docker-publish.yml")

    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true" in workflow
    assert (
        workflow.count(
            "docker/setup-qemu-action@06116385d9baf250c9f4dcb4858b16962ea869c3 # v4.1.0"
        )
        == 2
    )
    assert (
        workflow.count(
            "docker/setup-buildx-action@d7f5e7f509e45cec5c76c4d5afdd7de93d0b3df5 # v4.1.0"
        )
        == 2
    )
    assert (
        "docker/login-action@650006c6eb7dba73a995cc03b0b2d7f5ca915bee # v4.2.0"
        in workflow
    )
    assert (
        "docker/metadata-action@80c7e94dd9b9319bd5eb7a0e0fe9291e23a2a2e9 # v6.1.0"
        in workflow
    )
    assert (
        workflow.count(
            "docker/build-push-action@f9f3042f7e2789586610d6e8b85c8f03e5195baf # v7.2.0"
        )
        == 2
    )
    push_block = workflow.split("push:", 1)[1].split("pull_request:", 1)[0]
    pull_request_block = workflow.split("pull_request:", 1)[1].split("permissions:", 1)[
        0
    ]
    assert "tags:" in push_block
    assert "branches:" not in push_block
    assert "develop" in pull_request_block
    assert "ai_email_client-backend" in workflow
    assert "ai_email_client-frontend" in workflow
    assert workflow.count("image: naruon") == 2
    assert "push: false" in workflow
    assert "push: true" in workflow
    assert "type=semver" in workflow
    assert "type=ref,event=branch" not in workflow
    assert "deploy_preflight:" in workflow
    assert "AKS_KUBECONFIG_CONTENT: ${{ secrets.AKS_KUBECONFIG }}" in workflow
    assert "configured=false" in workflow
    assert "skipping deploy workflow" in workflow
    assert (
        "needs.deploy_preflight.outputs.aks_kubeconfig_configured == 'true'" in workflow
    )


def test_frontend_dockerfile_builds_and_starts_production_artifact() -> None:
    root_dockerfile = read_repo_text("Dockerfile")
    dockerfile = read_repo_text("frontend/Dockerfile")
    docker_publish_workflow = read_repo_text(".github/workflows/docker-publish.yml")
    frontend_deployment = read_repo_text("k8s/frontend-deployment.yaml")
    package_json = read_repo_text("frontend/package.json")

    assert '"packageManager": "pnpm@11.5.3"' in package_json
    assert "NEXT_PUBLIC_API_URL" not in root_dockerfile
    assert "NEXT_PUBLIC_API_URL" not in dockerfile
    assert "NEXT_PUBLIC_API_URL" not in docker_publish_workflow
    assert "NEXT_PUBLIC_API_URL" not in frontend_deployment
    assert "BACKEND_INTERNAL_URL" in frontend_deployment
    assert "ALLOW_DOCKER_BACKEND_INTERNAL_URL" in frontend_deployment
    assert "BACKEND_INTERNAL_URL" in dockerfile
    assert dockerfile.index("BACKEND_INTERNAL_URL is intentionally runtime-only") < (
        dockerfile.index("RUN pnpm run build")
    )
    assert "pnpm run build" in dockerfile
    assert "ENV POSTCSS_WORKERS=1" in dockerfile
    assert "ENV DISABLE_POSTCSS_WORKERS=true" in dockerfile
    assert (
        'CMD sh -c "exec ./node_modules/.bin/next start --hostname 0.0.0.0 --port ${PORT:-3000}"'
        in dockerfile
    )
    assert "pnpm run start" not in dockerfile
    assert "pnpm run dev" not in dockerfile


def test_backend_dockerfile_uses_modern_env_syntax() -> None:
    dockerfile = read_repo_text("Dockerfile")

    assert_dockerfile_stage_from(dockerfile, "python:3.14-slim", "backend-runtime")
    assert "ENV PYTHONDONTWRITEBYTECODE=1" in dockerfile
    assert "ENV PYTHONUNBUFFERED=1" in dockerfile
    assert "pnpm install --frozen-lockfile" in dockerfile
    assert "pnpm run build" in dockerfile
    assert "FROM backend-runtime" in dockerfile
    # Node binary is copied into /app/bin (owned by appuser) to avoid USER root.
    assert (
        "COPY --from=frontend-builder --chown=appuser:appuser /usr/local/bin/node /app/bin/node"
        in dockerfile
    )
    assert "ENV PATH=/app/bin:$PATH" in dockerfile
    assert "USER root" not in dockerfile
    assert "nodejs" not in dockerfile
    assert "ENV PYTHONDONTWRITEBYTECODE 1" not in dockerfile
    assert "ENV PYTHONUNBUFFERED 1" not in dockerfile
    assert "secrets.token_hex" not in dockerfile
    assert "ENV DATABASE_URL=" not in dockerfile
    assert '"/app/scripts/docker_entrypoint.sh"' in dockerfile
    assert "RUN chmod +x /app/scripts/docker_entrypoint.sh" in dockerfile
    assert "useradd --system --create-home --home-dir /home/appuser" in dockerfile
    backend_cmd = 'CMD ["python", "scripts/start_backend.py", "--host", "0.0.0.0", "--port", "8000"]'
    assert dockerfile.find("USER appuser") < dockerfile.find(backend_cmd)
    assert dockerfile.rfind("USER appuser") < dockerfile.find(
        'CMD ["/app/scripts/docker_entrypoint.sh"]'
    )
    assert "COPY scripts/start_combined.sh" not in dockerfile
    assert "RUN echo '#!/bin/bash" not in dockerfile
    assert "uvicorn" not in dockerfile.split("CMD", 1)[1]


def test_combined_image_start_script_preflights_env_and_logs_service_exit() -> None:
    start_script = read_repo_text("backend/scripts/docker_entrypoint.sh")

    assert (
        "for var in DATABASE_URL AUTH_SESSION_HMAC_SECRET ENCRYPTION_KEY"
        in start_script
    )
    assert "Fernet.generate_key()" in start_script
    assert "validate_auth_session_hmac_secret_value" in start_script
    assert "AUTH_SESSION_HMAC_SECRET is invalid" in start_script
    assert "database migration failed" in start_script
    assert "Backend and frontend will not start." in start_script
    assert "Starting backend (uvicorn :8000)" in start_script
    assert "Starting frontend (next start :3000)" in start_script
    assert 'wait -n "$backend_pid" "$frontend_pid"' in start_script
    assert "Backend (:8000) exited with code" in start_script
    assert "Frontend (:3000) exited with code" in start_script


def test_deepwiki_qna_gap_execution_tracker_covers_requested_scope() -> None:
    tracker = read_repo_text("docs/development/deepwiki-qna-gap-execution-track.md")

    required_items = {
        "dav-propfind-db-backed",
        "alembic-migrations",
        "oidc-production-multi-user",
        "self-hosted-connector-adapters",
        "caldav-webdav-provider-write",
        "ready-soon-ui-removal",
        "postgresql-ha-physical-replication",
        "pop3-runtime-sync",
        "reply-sla-scheduler",
        "data-workspace-documents",
        "connector-apm-history",
        "sender-dag-source-filtering",
    }
    for item in required_items:
        assert item in tracker

    required_evidence = [
        "backend/api/dav.py",
        "backend/tests/test_dav_api.py",
        "backend/alembic/versions/0001_initial_control_plane.py",
        "backend/api/auth.py",
        "backend/runner/local_mail_adapters.py",
        "backend/runner/local_dav_adapters.py",
        "backend/api/calendar.py",
        "backend/api/webdav.py",
        "backend/api/observability.py",
        "backend/services/provider_writeback_retry_service.py",
        "backend/main.py",
        "backend/alembic/versions/0002_provider_writeback_retry_queue.py",
        "backend/tests/test_provider_writeback_retry_service.py",
        "backend/tests/test_observability_api.py",
        "backend/tests/test_main.py",
        "frontend/src/components/CalendarLayout.tsx",
        "frontend/src/app/calendar/page.test.tsx",
        "frontend/src/components/TasksLayout.tsx",
        "frontend/src/app/tasks/page.test.tsx",
        "frontend/src/components/DataLayout.tsx",
        "frontend/src/components/SettingsLayout.tsx",
        "frontend/src/components/SettingsLayout.test.tsx",
        "docs/operations/postgresql-physical-replication.md",
        "docs/operations/postgresql-ha-drill-20260615.md",
        "scripts/postgres_ha_drill.sh",
        "scripts/postgres-ha/init-primary-replication.sh",
        "backend/tests/test_infra_evaluations.py",
        "backend/core/config.py",
        "backend/db/session.py",
        "backend/tests/test_db_session.py",
        "backend/services/pop3_worker.py",
        "backend/services/reply_sla_scheduler.py",
        "backend/api/data.py",
        "backend/api/observability.py",
        "backend/api/ontology.py",
    ]
    for evidence_path in required_evidence:
        assert evidence_path in tracker

    assert "remaining_executable_goal" in tracker
    assert "verification_command" in tracker


def test_backend_compose_commands_use_startup_preflight() -> None:
    compose = read_repo_text("docker-compose.yml")
    live_e2e_compose = read_repo_text("docker-compose.live-e2e.yml")

    backend_block = compose.split("  backend:", 1)[1].split("  frontend:", 1)[0]
    assert "target: backend-runtime" in backend_block
    assert 'DEBUG: "false"' in backend_block
    assert "DEBUG: true" not in backend_block
    assert (
        "DATABASE_URL: postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@db:5432/ai_email"
        in backend_block
    )
    assert "READONLY_DATABASE_URL: ${READONLY_DATABASE_URL:-}" in backend_block
    assert "AUTH_SESSION_HMAC_SECRET: ${AUTH_SESSION_HMAC_SECRET}" in backend_block
    assert "ENCRYPTION_KEY: ${ENCRYPTION_KEY}" in backend_block
    assert "- AUTH_SESSION_HMAC_SECRET" not in backend_block
    assert "- ENCRYPTION_KEY" not in backend_block
    assert "python scripts/migrate_db.py && python scripts/start_backend.py" in compose
    assert "scripts/start_backend.py" in live_e2e_compose
    assert "Dockerfile.ollama" in live_e2e_compose
    assert (
        "DATABASE_URL: ${DATABASE_URL:?Set DATABASE_URL for live E2E}"
        in live_e2e_compose
    )
    assert "postgresql+asyncpg://" not in live_e2e_compose
    assert '"127.0.0.1:18080:8080"' in live_e2e_compose
    assert 'OLLAMA_NO_CLOUD: "true"' in compose
    assert 'OLLAMA_NO_CLOUD: "true"' in live_e2e_compose
    assert "OPENAI_BASE_URL: http://ollama:11434/v1" in live_e2e_compose
    assert "OPENAI_MODEL: gemma4:e2b-it-qat" in live_e2e_compose
    assert "OPENAI_EMBEDDING_MODEL: embeddinggemma" in live_e2e_compose
    assert "live-e2e-state:/live-e2e-state" in live_e2e_compose
    assert "touch /live-e2e-state/migrated" in live_e2e_compose
    assert "touch /live-e2e-state/seeded" in live_e2e_compose
    assert "Required startup marker missing: $$marker" in live_e2e_compose
    assert "  live-e2e-state:" in live_e2e_compose
    live_backend_block = live_e2e_compose.split("  backend:", 1)[1].split(
        "  frontend:", 1
    )[0]
    assert "ALLOWED_CORS_ORIGINS: http://127.0.0.1:18080" in live_backend_block
    live_frontend_block = live_e2e_compose.split("  frontend:", 1)[1].split(
        "  nginx:", 1
    )[0]
    assert "NEXT_PUBLIC_API_URL" not in live_frontend_block
    assert "BACKEND_INTERNAL_URL: http://backend:8000" in live_frontend_block
    assert 'ALLOW_DOCKER_BACKEND_INTERNAL_URL: "1"' in live_frontend_block
    assert "TRUSTED_FRONTEND_ORIGINS: http://127.0.0.1:18080" in live_frontend_block
    live_nginx = read_repo_text("tests/live/nginx.conf")
    assert "proxy_read_timeout 600s" in live_nginx
    assert (
        'add_header Referrer-Policy "strict-origin-when-cross-origin" always;'
        in live_nginx
    )
    assert 'add_header X-Content-Type-Options "nosniff" always;' in live_nginx
    assert 'add_header X-Frame-Options "DENY" always;' in live_nginx
    assert "upstream live_backend" not in live_nginx
    api_location = live_nginx.split("    location /api/ {", 1)[1].split("    }", 1)[0]
    root_location = live_nginx.split("    location / {", 1)[1].split("    }", 1)[0]
    for location in (api_location, root_location):
        assert "proxy_set_header Host $http_host;" in location
        assert "proxy_set_header X-Forwarded-Host $http_host;" in location
        assert "proxy_set_header X-Real-IP $remote_addr;" in location
        assert (
            "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in location
        )
        assert "proxy_set_header X-Forwarded-Proto $scheme;" in location
        assert "proxy_set_header Upgrade $http_upgrade;" in location
        assert 'proxy_set_header Connection "upgrade";' in location
    assert "proxy_pass http://live_frontend;" in api_location
    assert "proxy_pass http://live_backend;" not in api_location


def test_compose_log_scanner_exists_for_warning_policy() -> None:
    scanner = read_repo_text("scripts/check_compose_logs.py")

    assert "warning|warn|deprecated|notice|fatal|denied|unable" in scanner
    assert "allowed_count" in scanner
    assert "unexpected_count" in scanner
    assert "Use --ui/--no-ui" in scanner
    assert "or deprecated --webui/--no-webui" in scanner


def test_compose_log_scanner_allows_nginx_stderr_startup_notices() -> None:
    nginx_startup_lines = "\n".join(
        [
            '2026/06/13 06:25:27 [notice] 1#1: using the "epoll" event method',
            "2026/06/13 06:25:27 [notice] 1#1: nginx/1.27.5",
            "2026/06/13 06:25:27 [notice] 1#1: built by gcc 14.2.0 (Alpine 14.2.0)",
            "2026/06/13 06:25:27 [notice] 1#1: OS: Linux 6.19.7-200.fc43.aarch64",
            "2026/06/13 06:25:27 [notice] 1#1: getrlimit(RLIMIT_NOFILE): 524288:524288",
            "2026/06/13 06:25:27 [notice] 1#1: start worker processes",
            "2026/06/13 06:25:27 [notice] 1#1: start worker process 16",
        ]
    )

    scanner_script = REPO_ROOT / "scripts/check_compose_logs.py"
    spec = importlib.util.spec_from_file_location("check_compose_logs", scanner_script)
    assert spec and spec.loader, "Failed to load module"
    check_compose_logs_module = importlib.util.module_from_spec(spec)
    sys.modules["check_compose_logs"] = check_compose_logs_module
    spec.loader.exec_module(check_compose_logs_module)

    unexpected, allowed = check_compose_logs_module.scan_lines(
        nginx_startup_lines.splitlines()
    )
    assert not unexpected, f"Unexpected lines found: {unexpected}"
    assert len(allowed) == 7, f"Expected 7 allowed lines, got {len(allowed)}"


def test_strix_workflow_uses_github_models_default_and_narrow_warning_filter() -> None:
    workflow = read_repo_text(".github/workflows/strix.yml")
    gate_script = read_repo_text("scripts/ci/strix_quick_gate.sh")

    assert "format('pr-{0}', github.event.pull_request.number)" in workflow
    assert "format('pr-{0}', github.event.inputs.pr_number)" in workflow
    assert "|| github.ref" in workflow
    push_block = workflow.split("push:", 1)[1].split("pull_request_target:", 1)[0]
    assert "develop" in push_block
    assert "master" in push_block
    assert "cancel-in-progress: false" in workflow
    assert "models: read" in workflow
    assert "provider_mode=github_models" in workflow
    assert "strix_llm:" in workflow
    assert "github.event.inputs.strix_llm || 'openai/gpt-5'" in workflow
    assert 'python-version: "3.13"' in workflow
    assert "secrets.STRIX_LLM ||" not in workflow
    assert "https://models.github.ai/inference" in workflow
    assert "LLM_API_BASE_FILE" in workflow
    assert (
        "STRIX_GITHUB_MODELS_TOKEN is required for GitHub Models Strix scans"
        in workflow
    )
    assert "secrets.STRIX_GITHUB_MODELS_TOKEN || github.token" in workflow
    assert (
        "steps.gate.outputs.provider_mode == 'github_models' && (secrets.STRIX_GITHUB_MODELS_TOKEN || github.token)"
        in workflow
    )
    assert "openai/gpt-5-mini* | openai/gpt-5-nano*" in workflow
    assert "vertex_ai/gemini-3.1-pro-preview-customtools" in workflow
    assert (
        "secrets.STRIX_LLM == 'vertex_ai/gemini-3.1-pro-preview-customtools' "
        "&& 'vertex_ai/gemini-2.5-flash'" not in workflow
    )
    assert 'STRIX_FAIL_ON_PROVIDER_SIGNAL: "1"' in workflow
    assert 'STRIX_VERTEX_FALLBACK_MODELS: ""' in workflow
    assert (
        "github_models/deepseek/deepseek-r1-0528 "
        "github_models/deepseek/deepseek-v3-0324"
    ) in workflow
    assert (
        "vertex_ai/gemini-3.1-pro-preview-customtools | vertex_ai/gemini-2.5-flash"
        in workflow
    )
    assert "vertex_ai/* | vertex_ai_beta/*" not in workflow
    assert "PYTHONWARNINGS:" not in workflow
    assert (
        'child_env["PYTHONWARNINGS"] = '
        '"ignore:Pydantic serializer warnings:UserWarning:pydantic.main"' in gate_script
    )
    assert "ignore::UserWarning" not in workflow


def test_strix_workflow_validates_vertex_credentials_before_export() -> None:
    workflow = read_repo_text(".github/workflows/strix.yml")

    assert 'credentials_path.read_text(encoding="utf-8")' in workflow
    assert "object_pairs_hook=reject_duplicate_json_keys" in workflow
    assert 'raise ValueError("duplicate credential key")' in workflow
    assert (
        "except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):"
        in workflow
    )
    assert (
        "GCP_SA_KEY must be valid service account JSON for Vertex AI Strix scans."
        in workflow
    )
    assert "if not isinstance(credentials, dict):" in workflow
    assert "GCP_SA_KEY must be a JSON object for Vertex AI Strix scans." in workflow
    assert "json.loads(credentials_path.read_text())" not in workflow


def test_opencode_review_fallbacks_do_not_emit_successful_error_annotations() -> None:
    workflow = read_repo_text(".github/workflows/opencode-review.yml")

    assert "continue-on-error: true" not in workflow
    assert 'printf \'review_status=%s\\n\' "$1" >>"$GITHUB_OUTPUT"' in workflow
    assert 'record_review_status "failed"' in workflow
    assert 'record_review_status "success"' in workflow
    assert (
        "steps.opencode_review_primary.outputs.review_status != 'success'" in workflow
    )
    assert (
        "steps.opencode_review_primary.outputs.review_status == 'success'" in workflow
    )
    assert "steps.opencode_review_primary.outcome" not in workflow
    assert "steps.opencode_review_fallback.outcome" not in workflow
    assert "steps.opencode_review_second_fallback.outcome" not in workflow


def _bash_executable() -> str:
    bash = shutil.which("bash")
    assert bash is not None, "bash executable is required for governance script tests"
    return bash


def _run_emit_opencode_failed_check_fallback(
    evidence_file: Path, repo_root: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        [
            _bash_executable(),
            str(
                REPO_ROOT / "scripts/ci/emit_opencode_failed_check_fallback_findings.sh"
            ),
            str(evidence_file),
            str(repo_root),
        ],
        text=True,
        capture_output=True,
        check=True,
    )


def _run_validate_opencode_failed_check_review(
    control_file: Path, failed_checks_file: Path, evidence_file: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        [
            _bash_executable(),
            str(REPO_ROOT / "scripts/ci/validate_opencode_failed_check_review.sh"),
            str(control_file),
            str(failed_checks_file),
            str(evidence_file),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_validation_succeeds(
    control_file: Path,
    control_data: dict[str, Any],
    failed_checks_file: Path,
    evidence_file: Path,
) -> None:
    control_file.write_text(json.dumps(control_data), encoding="utf-8")
    validation = _run_validate_opencode_failed_check_review(
        control_file, failed_checks_file, evidence_file
    )
    assert validation.returncode == 0, (
        f"stdout:\n{validation.stdout}\nstderr:\n{validation.stderr}"
    )


def _assert_validation_fails_with(
    control_file: Path,
    control_data: dict[str, Any],
    failed_checks_file: Path,
    evidence_file: Path,
    expected_error: str,
    expected_returncode: int = 4,
) -> None:
    control_file.write_text(json.dumps(control_data), encoding="utf-8")
    validation = _run_validate_opencode_failed_check_review(
        control_file, failed_checks_file, evidence_file
    )
    failure_output = f"stdout:\n{validation.stdout}\nstderr:\n{validation.stderr}"
    assert validation.returncode == expected_returncode, failure_output
    assert expected_error in validation.stdout, failure_output


def _setup_strix_failed_check_evidence(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo_root = tmp_path / "repo"
    auth_file = repo_root / "backend" / "app" / "auth.py"
    page_file = repo_root / "frontend" / "src" / "app" / "page.tsx"
    workflow_file = repo_root / ".github" / "workflows" / "strix.yml"
    auth_file.parent.mkdir(parents=True)
    page_file.parent.mkdir(parents=True)
    workflow_file.parent.mkdir(parents=True)
    auth_file.write_text("\n".join(f"# auth line {line}" for line in range(1, 180)))
    page_file.write_text("\n".join(f"// page line {line}" for line in range(1, 80)))
    workflow_file.write_text("STRIX_FALLBACK_MODELS: deepseek/deepseek-r1-0528\n")

    evidence_file = tmp_path / "failed-check-evidence.md"
    failed_checks_file = tmp_path / "failed-checks.md"
    failed_checks_file.write_text("- Strix Security Scan/strix: FAILURE\n")
    evidence_file.write_text(
        """
# Failed GitHub Check Evidence

## Failed check: Strix Security Scan/strix

### Strix vulnerability report window 1 (log lines 100-210)

```text
Strix run failed for model 'openai/gpt-5' after 145s (exit code 1).
│  Vulnerability Report                                                        │
│  Title: Authentication Bypass via X-Dev-User Header                          │
│  Severity: CRITICAL                                                          │
│  Endpoint: /api/me                                                           │
│  Method: GET                                                                 │
│  Code Locations                                                              │
│    Location 1: backend/app/auth.py:132-135                                   │
│  Model deepseek/deepseek-r1-0528                                             │
│  Vulnerabilities 1                                                           │
```

### Strix vulnerability report window 2 (log lines 220-340)

```text
Strix run failed for model 'deepseek/deepseek-r1-0528' after 206s (exit code 2).
│  Vulnerability Report                                                        │
│  Title: Frontend Security Issues: XSS and Insecure Data Handling             │
│  Severity: HIGH                                                              │
│  Endpoint: /                                                                 │
│  Method: GET                                                                 │
│  Code Locations                                                              │
│    Location 1: frontend/src/app/page.tsx:8-12                                │
│  Model deepseek/deepseek-v3-0324                                             │
│  Vulnerabilities 1                                                           │
```
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return repo_root, evidence_file, failed_checks_file


def test_opencode_strix_failed_check_review_keeps_late_model_reports_distinct(
    tmp_path: Path,
) -> None:
    agents = read_repo_text("AGENTS.md")
    repo_root, evidence_file, _ = _setup_strix_failed_check_evidence(tmp_path)

    fallback = _run_emit_opencode_failed_check_fallback(evidence_file, repo_root)

    assert (
        "Strix report from deepseek/deepseek-r1-0528: "
        "Authentication Bypass via X-Dev-User Header"
    ) in fallback.stdout
    assert (
        "Strix report from deepseek/deepseek-v3-0324: "
        "Frontend Security Issues: XSS and Insecure Data Handling"
    ) in fallback.stdout
    assert (
        "Strix report from openai/gpt-5: Authentication Bypass" not in fallback.stdout
    )
    assert fallback.stdout.count("Strix report from deepseek/") == 2
    normalized_agents = " ".join(agents.split())
    assert "Strix logs may print the report's `Model ...` line after" in agents
    assert "not to a previous retry attempt" in normalized_agents


def test_opencode_strix_failed_check_review_accepts_distinct_model_reports(
    tmp_path: Path,
) -> None:
    _, evidence_file, failed_checks_file = _setup_strix_failed_check_evidence(tmp_path)

    good_control_file = tmp_path / "good-control.json"
    _assert_validation_succeeds(
        good_control_file,
        {
            "summary": "Strix failed with two fallback model reports.",
            "reason": "Strix Security Scan failed",
            "findings": [
                {
                    "path": "backend/app/auth.py",
                    "line": 132,
                    "severity": "CRITICAL",
                    "title": "Strix report from deepseek/deepseek-r1-0528",
                    "problem": (
                        "Strix Security Scan/strix reported "
                        "Authentication Bypass via X-Dev-User Header. "
                        "Severity: CRITICAL. Endpoint: /api/me. Method: GET. "
                        "Code location backend/app/auth.py:132-135."
                    ),
                    "root_cause": "deepseek/deepseek-r1-0528 report evidence",
                    "fix_direction": "Remove X-Dev-User trust from this line.",
                    "regression_test_direction": "Cover /api/me auth bypass.",
                    "suggested_diff": "- old\n+ new",
                },
                {
                    "path": "frontend/src/app/page.tsx",
                    "line": 8,
                    "severity": "HIGH",
                    "title": "Strix report from deepseek/deepseek-v3-0324",
                    "problem": (
                        "Strix Security Scan/strix reported Frontend Security "
                        "Issues: XSS and Insecure Data Handling. Severity: HIGH. "
                        "Endpoint: /. Method: GET. Code location "
                        "frontend/src/app/page.tsx:8-12."
                    ),
                    "root_cause": "deepseek/deepseek-v3-0324 report evidence",
                    "fix_direction": "Patch the frontend render boundary.",
                    "regression_test_direction": "Cover escaped page output.",
                    "suggested_diff": "- old\n+ new",
                },
            ],
        },
        failed_checks_file,
        evidence_file,
    )


def test_opencode_strix_failed_check_review_rejects_collapsed_model_reports(
    tmp_path: Path,
) -> None:
    _, evidence_file, failed_checks_file = _setup_strix_failed_check_evidence(tmp_path)

    collapsed_control_file = tmp_path / "collapsed-control.json"
    _assert_validation_fails_with(
        collapsed_control_file,
        {
            "summary": "Strix failed with two fallback model reports.",
            "reason": "Strix Security Scan failed",
            "findings": [
                {
                    "path": "backend/app/auth.py",
                    "line": 132,
                    "severity": "CRITICAL",
                    "title": "Strix reports from deepseek/deepseek-r1-0528 and deepseek/deepseek-v3-0324",
                    "problem": (
                        "Authentication Bypass via X-Dev-User Header; "
                        "Frontend Security Issues: XSS and Insecure Data Handling. "
                        "Severity: CRITICAL HIGH. Endpoints: /api/me and /. "
                        "Method: GET. Locations: backend/app/auth.py:132-135 "
                        "and frontend/src/app/page.tsx:8-12."
                    ),
                    "root_cause": "Collapsed both Strix model reports into one finding.",
                    "fix_direction": "Patch both reported locations.",
                    "regression_test_direction": "Cover both reports.",
                    "suggested_diff": "- old\n+ new",
                }
            ],
        },
        failed_checks_file,
        evidence_file,
        expected_error="FAILED_CHECK_EVIDENCE_NOT_REFERENCED",
    )


def test_opencode_strix_failed_check_review_model_before_title_attributed_correctly(
    tmp_path: Path,
) -> None:
    """Model line appearing before Title inside a report window must override
    a prior failed-model mention from the same window header.

    This complements test_opencode_strix_failed_check_review_keeps_late_model_reports_distinct
    which covers Model appearing *after* code locations.  Together the two tests
    ensure both orderings (Model-before-Title and Model-after-Code-Locations) are
    handled correctly regardless of a prior 'Strix run failed for model' line in
    the same window.
    """
    repo_root = tmp_path / "repo"
    auth_file = repo_root / "backend" / "app" / "auth.py"
    auth_file.parent.mkdir(parents=True)
    auth_file.write_text("\n".join(f"# auth line {line}" for line in range(1, 180)))

    evidence_file = tmp_path / "failed-check-evidence.md"
    failed_checks_file = tmp_path / "failed-checks.md"
    failed_checks_file.write_text("- Strix Security Scan/strix: FAILURE\n")
    evidence_file.write_text(
        """
# Failed GitHub Check Evidence

## Failed check: Strix Security Scan/strix

### Strix vulnerability report window 1 (log lines 100-210)

```text
Strix run failed for model 'openai/gpt-5' after 145s (exit code 1).
│  Model deepseek/deepseek-r1-0528                                            │
│  Vulnerability Report                                                       │
│  Title: Auth Bypass via Header                                              │
│  Severity: CRITICAL                                                         │
│  Endpoint: /api/me                                                          │
│  Method: GET                                                                │
│  Code Locations                                                             │
│    Location 1: backend/app/auth.py:132-135                                  │
│  Vulnerabilities 1                                                          │
```
""".strip()
        + "\n",
        encoding="utf-8",
    )

    fallback = _run_emit_opencode_failed_check_fallback(evidence_file, repo_root)

    assert (
        "Strix report from deepseek/deepseek-r1-0528: Auth Bypass via Header"
    ) in fallback.stdout
    assert "openai/gpt-5" not in fallback.stdout

    good_control_file = tmp_path / "good-control.json"
    _assert_validation_succeeds(
        good_control_file,
        {
            "summary": "Strix failed with deepseek fallback report.",
            "reason": "Strix Security Scan failed",
            "findings": [
                {
                    "path": "backend/app/auth.py",
                    "line": 132,
                    "severity": "CRITICAL",
                    "title": "Strix report from deepseek/deepseek-r1-0528",
                    "problem": (
                        "Strix Security Scan/strix reported "
                        "Auth Bypass via Header. "
                        "Severity: CRITICAL. Endpoint: /api/me. Method: GET. "
                        "Code location backend/app/auth.py:132-135."
                    ),
                    "root_cause": "deepseek/deepseek-r1-0528 report evidence",
                    "fix_direction": "Remove the bypass.",
                    "regression_test_direction": "Cover auth bypass.",
                    "suggested_diff": "- old\n+ new",
                }
            ],
        },
        failed_checks_file,
        evidence_file,
    )

    wrong_attribution_file = tmp_path / "wrong-control.json"
    _assert_validation_fails_with(
        wrong_attribution_file,
        {
            "summary": "Strix failed.",
            "reason": "Strix Security Scan failed",
            "findings": [
                {
                    "path": "backend/app/auth.py",
                    "line": 132,
                    "severity": "CRITICAL",
                    "title": "Strix report from openai/gpt-5",
                    "problem": (
                        "Strix Security Scan/strix reported Auth Bypass via Header. "
                        "Severity: CRITICAL."
                    ),
                    "root_cause": "openai/gpt-5 report evidence",
                    "fix_direction": "Remove the bypass.",
                    "regression_test_direction": "Cover auth bypass.",
                    "suggested_diff": "- old\n+ new",
                }
            ],
        },
        failed_checks_file,
        evidence_file,
        expected_error="FAILED_CHECK_EVIDENCE_NOT_REFERENCED",
    )


def test_pr_governance_uses_metadata_only_events_without_checkout_or_admin_merge() -> (
    None
):
    workflow = read_repo_text(".github/workflows/pr-governance.yml")
    gate_script = read_repo_text("scripts/ci/pr_governance_gate.sh")
    combined = f"{workflow}\n{gate_script}"

    assert "pull_request_target:" in workflow
    assert "workflow_run:" in workflow
    assert "check_run:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "Strix Security Scan" in workflow
    assert "- strix" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "trusted-governance" in workflow
    assert ".base.sha" in workflow
    assert "github.sha" not in workflow
    assert "tarball/${trusted_ref}" in workflow
    assert "gh_api_with_retry" in workflow
    assert "GitHub API request attempt" in workflow
    assert "Trusted governance ref must be a full commit SHA" in workflow
    assert "trusted_archive_candidate" in workflow
    assert "tar -tzf" in workflow
    assert "Trusted governance archive materialization attempt" in workflow
    assert "after 4 attempts" in workflow
    assert 'bash "$GOVERNANCE_GATE"' in workflow
    assert "CHECK_RUN_PR_NUMBER" in workflow
    assert "headRefOid" in gate_script
    assert "mergeStateStatus" in gate_script
    assert "gh pr checks" in gate_script and "--required" in gate_script
    assert "check-runs" in gate_script
    assert "Review skipped" in gate_script
    assert "CodeRabbit" in gate_script or "coderabbit" in gate_script
    assert "BEHIND" in gate_script
    assert "app.slug" in gate_script
    assert "coderabbitai" in gate_script
    assert "/issues/${PR_NUMBER}/comments" in gate_script
    assert "COMMENT_MARKER" in gate_script
    assert "Waiting for" in gate_script
    assert "reviewThreads" in gate_script
    assert "CHANGES_REQUESTED" in gate_script
    assert "gh pr merge" not in gate_script
    assert "--match-head-commit" not in gate_script
    assert "actions/checkout" not in combined
    assert "@coderabbitai ignore" not in combined
    assert "git clone" not in combined
    assert "--admin" not in combined
    assert "contents: write" not in combined
    assert "continue-on-error: true" not in combined
    assert "dismiss" not in combined.lower()


def test_coderabbit_approval_is_decoupled_from_github_checks() -> None:
    config = read_repo_text(".coderabbit.yaml")
    policy = read_repo_text("docs/development/merge-gate-policy.md")
    agents = read_repo_text("AGENTS.md")

    assert "request_changes_workflow: true" in config
    assert "github-checks:" in config
    assert "enabled: false" in config
    assert "GitHub Checks integration stays disabled" in policy
    assert "GitHub Checks integration disabled" in agents


def test_agents_records_ghcr_visibility_publication_runbook() -> None:
    agents = read_repo_text("AGENTS.md")
    normalized_agents = " ".join(agents.split())

    assert "GHCR publishing evidence for the combined `naruon` image" in agents
    assert "REST Packages API" in agents
    assert "GraphQL package mutations" in agents
    assert "visibility: private" in agents
    assert "Package settings" in agents
    assert "Danger Zone" in agents
    assert "Change visibility" in normalized_agents
    assert "anonymous pull/token access" in agents
