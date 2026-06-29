## 2024-05-24 - Overly Permissive CORS Policy

**Vulnerability:** The CORS configuration in FastAPI allowed wildcards (`*`) for `allow_methods` and `allow_headers`.
**Learning:** This could permit unintended cross-origin interaction, potentially exposing the API to Cross-Site Request Forgery (CSRF) or unintended data exposure, particularly via custom headers or unconventional methods.
**Prevention:** Always restrict `allow_methods` and `allow_headers` in CORS policies to the exact methods and headers required by the application.
## 2026-05-28 - Missing Next.js Security Headers
**Vulnerability:** The Next.js frontend was missing critical HTTP security headers (Content-Security-Policy, X-Content-Type-Options, X-Frame-Options, Strict-Transport-Security).
**Learning:** Security headers should be explicitly configured in Next.js applications via the `headers()` method in `next.config.ts`, as they are not included by default.
**Prevention:** Always enforce a strong CSP and other security headers at the application framework level, even if the application is purely API-driven.

## 2025-02-24 - [DAV Path Traversal Vulnerability]
**Vulnerability:** A path traversal vulnerability existed in the `/dav/{path:path}` endpoint where `_dav_path_owner_user_id` extracted the owner user ID using `path.partition("/")` without validating or normalizing `..` segments.
**Learning:** This allowed an attacker to supply a path like `my_user_id/../other_user_id/projects`, tricking the authorization check `_ensure_dav_owner_scope` into passing because the first segment matched their authenticated `user_id`. The remaining path could then be used downstream to access resources of `other_user_id`. When testing this against FastAPI's TestClient, the TestClient normalizes `../` automatically; `..%2F` must be used to test the router correctly.
**Prevention:** Always validate or normalize dynamic paths used for authorization constraints, explicitly rejecting paths containing traversal segments like `..` before parsing hierarchical data.
## 2026-06-20 - Authorization Bypass in Access Policy Evaluation
**Vulnerability:** System admin and platform admin roles could bypass the organization boundary checks and the resource ownership checks in `evaluate_access()` inside `backend/services/access_policy.py`.
**Learning:** This insecure authorization logic allowed a system administrator intended for global operations to have unconstrained horizontal and vertical privilege escalation over arbitrary resources owned by other organizations and other users.
**Prevention:** Access policy evaluations must unconditionally evaluate constraints like `organization_id` matching and `owner_id` matching, applying authorization boundaries strictly independent of the role unless explicitly designed to supersede those checks for specific resources.
## 2025-02-20 - MD5 to SHA-256 for Security Scanner Compliance
**Vulnerability:** MD5 used for hashing random parameters for DB table unique IDs.
**Learning:** Using MD5, even for non-cryptographic purposes like generating unique IDs from randomness, triggers security scanners. Cryptographically weak functions like MD5 should not be used when stronger ones are available.
**Prevention:** In SQL queries and backend code, prefer using `encode(sha256((...)::bytea), 'hex')` over `md5(...)` to generate deterministic hashes or unique IDs to maintain compliance and security.

## 2026-06-20 - Missing Auth on update_tenant_config (Already Mitigated)
**Vulnerability:** A previous state of the codebase was reported to be missing `Depends(get_auth_context)` on `update_tenant_config`.
**Learning:** `auth_ctx: AuthContext = Depends(get_auth_context)` is already correctly implemented in the endpoint signature.
**Prevention:** Always rely on FastAPI dependency injection to enforce endpoint security.

## 2024-05-28 - [Subprocess path execution vulnerability fix]
**Vulnerability:** [Bandit B607 Starting a process with a partial executable path and B603 subprocess call without shell equals true]
**Learning:** [Using partial paths with subprocess like 'bash' instead of absolute paths allows potential path manipulation attacks if PATH is altered. Executing python scripts with subprocess.run introduces process spawning overhead and could expose untrusted execution depending on how the interpreter executes inputs.]
**Prevention:** [Use shutil.which("bash") or absolute paths. For executing local python scripts from tests, use importlib to dynamically load the module and execute the target function directly instead of spawning a new python subprocess, which avoids B603 entirely and is generally more efficient.]

## 2026-06-20 - [Fix Subprocess Path Execution Vulnerability]
**Vulnerability:** B607: Starting a process with a partial executable path & B603: subprocess call without shell equals true.
**Learning:** Using `subprocess.run` with partial executable paths (like `"bash"`) could allow path injection attacks if the `PATH` environment variable is manipulated. Also calling local Python scripts using `subprocess` can be inefficient and triggers B603 warnings.
**Prevention:** Always use absolute paths (e.g. `shutil.which("bash")`) for external command execution. For local Python scripts, use `importlib` to dynamically import the module and invoke its `main()` function directly to avoid spawning new subprocesses.

## 2025-06-19 - Inconsistent Authorization in AI Hub

**Vulnerability:** The AI Hub's list prompts endpoint (`_list_prompts` in `backend/api/ai_hub.py`) strictly filtered returned prompts by `created_by == auth_context.user_id`, ignoring the `is_shared` property which allows a prompt to be accessed globally. This resulted in a failure of access control policies because shared resources were effectively hidden from the surface, while directly accessible through other APIs.
**Learning:** Authorization and resource filtering must be consistently scoped across the system. Inconsistency leads to functional security bugs where visibility does not match explicit intent (e.g. sharing).
**Prevention:** Unify queries regarding scoping (e.g., using centralized helper functions for where-clauses) instead of redefining conditions per-endpoint. When creating models with boolean overrides for visibility like `is_shared`, ensure all read paths respect them.

## 2024-05-31 - Hardcoded Session Token in Tests
**Vulnerability:** Found hardcoded string `"header.payload.signature"` in multiple `.test.ts` files.
**Learning:** Even in test files, realistic-looking hardcoded tokens or secrets can be flagged by security scanners as hardcoded credentials. It is bad hygiene.
**Prevention:** Use explicitly fake and descriptive placeholder strings like `"test-header.test-payload.test-signature"` for token mocking in tests.

## 2026-06-20 - Hardcoded API Key for Testing
**Vulnerability:** Hardcoded API keys and passwords were found in `backend/tests/test_tenant_config_model.py` and `backend/tests/test_email_client_smtp.py`.
**Learning:** Hardcoded secrets in testing files can still leak into version control and potentially be used in production or misconfigured systems.
**Prevention:** Avoid hardcoding any secrets, even in test files. Use environment variables with default fallback values (e.g. `os.environ.get("TEST_KEY", "dummy-value")`).
## 2026-06-20 - [Fix CSRF Default-Allow Bypass]
**Vulnerability:** The API proxy's `sameOriginStateChangingRequest` function previously allowed state-changing requests if both `sec-fetch-site` and `origin` headers were missing, creating a potential CSRF vector if an attacker suppressed the Origin header.
**Learning:** Default-allow fallbacks for missing security metadata can silently bypass critical protections, especially when relying solely on cookie-based authentication.
**Prevention:** Always fail securely by defaulting to `false` when required origin/referer security metadata is absent, ensuring strict enforcement for state-changing operations.
## 2026-06-24 - Prevent URL-Encoded and Windows Path Traversal Bypass

**Vulnerability:** Path traversal in `_dav_path_owner_user_id` could be bypassed using doubly URL-encoded sequences (for example, `%252e%252e%252f`) and Windows-style backslashes.
**Learning:** Checking for traversal sequences after a single `/` split is insufficient if the input path can contain encoded payloads or alternative path separators.
**Prevention:** Recursively unquote DAV paths until stable, standardize backslashes to forward slashes, and reject `.` or `..` path segments before extracting authorization scope.

## 2026-06-22 - [Bandit B314: Insecure XML Parsing in Tests]
**Vulnerability:** `xml.etree.ElementTree.fromstring` was used to parse XML responses in tests (`backend/tests/test_dav_api.py`), triggering Bandit B314 (vulnerable to XML attacks).
**Learning:** Even in test environments parsing trusted responses, standard XML parsers trigger security scanners because they are inherently vulnerable to XML external entity (XXE) and billion laughs attacks.
**Prevention:** Always use `defusedxml` (`import defusedxml.ElementTree as ET`) as a drop-in replacement when parsing XML anywhere in the codebase to pass static analysis and enforce secure-by-default habits.

## 2026-06-24 - Missing Auth Session Verification for OIDC
**Vulnerability:** Session metadata validation skipped explicit issuer (`iss`) and audience (`aud`) checks whenever OIDC was globally configured, rather than checking claims against the verifier that actually accepted the token.
**Learning:** Security validation functions must use contextual verifier evidence instead of assuming that a global configuration flag describes the token path.
**Prevention:** Pass the session verifier into metadata validation, fail closed when OIDC issuer/client configuration is incomplete, and normalize OIDC audiences before checking membership.

## 2024-06-25 - [Fix Email SMTP CRLF Injection & Double Extension Upload]
**Vulnerability:** Attackers could inject arbitrary SMTP commands (e.g. MAIL FROM) using CRLF (\r\n) sequences in email subjects or recipients because `^[^\r\n]*$` validation in Pydantic wasn't catching all edge cases correctly. Attackers could also bypass file upload validations by providing double extensions (e.g., `malicious.exe.eml`).
**Learning:** Pydantic regex patterns might fall short for strict network protocol inputs like SMTP headers if improperly formulated or bypassed. Simple `.endswith()` checks for file uploads fail to prevent embedded dangerous extensions.
**Prevention:** Always use `@field_validator` with explicit `mode="before"` string matching for `chr(10)` and `chr(13)` across all user-controlled email header fields (to, subject, in_reply_to, references). Always tokenize uploaded filenames via `.split(".")` and reject if any segment matches a known dangerous extension (e.g., `.exe`, `.sh`).
