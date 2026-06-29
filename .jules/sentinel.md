## 2026-06-29 - Add CSRF Protection and File Size Limits
**Vulnerability:** Insecure file upload handling and CSRF vulnerability in multiple API endpoints.
**Learning:** React frontend fetch/axios requests need custom headers (`X-Requested-With: XMLHttpRequest`) to properly trigger CORS preflight logic or be identified securely by the backend logic preventing CSRF attacks. Also, file uploads must always have client-side (and server-side) size limits to prevent DoS.
**Prevention:** Always add a file size check before uploading files (e.g., `file.size > LIMIT`). Ensure API clients set `X-Requested-With` or custom CSRF tokens for state-changing endpoints.
