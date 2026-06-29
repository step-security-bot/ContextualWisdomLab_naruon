import { createHash } from "node:crypto";

import { NextRequest, NextResponse } from "next/server";

import {
  ANONYMOUS_SESSION_CLAIMS,
  SESSION_COOKIE_NAME,
  buildExpiredSessionCookieOptions,
  buildSessionCookieOptions,
  normalizeSessionToken,
  type SessionClaims,
} from "@/lib/session-cookie";
import { backendApiBaseUrl } from "@/lib/backend-url";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const fetchCache = "force-no-store";

const STATE_CHANGING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const NO_STORE_HEADERS = {
  "Cache-Control": "no-store",
};
const SESSION_VERIFICATION_RATE_LIMIT_WINDOW_MS = 60_000;
const SESSION_VERIFICATION_RATE_LIMIT_MAX_ATTEMPTS = 10;
const SESSION_VERIFICATION_RATE_LIMIT_MAX_BUCKETS = 4096;
const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001f\u007f]/;

type SessionVerificationBucket = {
  count: number;
  resetAt: number;
};

const sessionVerificationBuckets = new Map<string, SessionVerificationBucket>();

function firstHeaderValue(value: string | null): string | null {
  return value?.split(",")[0]?.trim() || null;
}

function forwardedProtocol(request: NextRequest): string {
  const proto = firstHeaderValue(request.headers.get("x-forwarded-proto"));
  if (proto === "http" || proto === "https") return proto;
  return request.nextUrl.protocol.replace(":", "");
}

function requestOriginCandidates(request: NextRequest): Set<string> {
  const origins = new Set([request.nextUrl.origin]);
  const proto = forwardedProtocol(request);
  const hosts = [
    firstHeaderValue(request.headers.get("x-forwarded-host")),
    firstHeaderValue(request.headers.get("host")),
  ];

  for (const host of hosts) {
    if (!host || CONTROL_CHARACTER_PATTERN.test(host)) continue;
    try {
      origins.add(new URL(`${proto}://${host}`).origin);
    } catch {
      // Ignore malformed proxy host metadata and keep the stricter origin set.
    }
  }

  return origins;
}

function sameOriginStateChangingRequest(request: NextRequest): boolean {
  if (!STATE_CHANGING_METHODS.has(request.method.toUpperCase())) return true;

  const fetchSite = request.headers.get("sec-fetch-site")?.trim().toLowerCase();
  if (fetchSite === "cross-site") return false;

  const origin = request.headers.get("origin");
  if (origin) {
    try {
      return requestOriginCandidates(request).has(new URL(origin).origin);
    } catch {
      return false;
    }
  }

  const referer = request.headers.get("referer");
  if (referer) {
    try {
      return requestOriginCandidates(request).has(new URL(referer).origin);
    } catch {
      return false;
    }
  }

  // Fail securely if neither Origin nor Referer is present
  return false;
}

function csrfRejectedResponse() {
  return NextResponse.json(
    {
      error_code: "csrf_origin_rejected",
      message: "Cross-site session updates are not allowed",
    },
    {
      status: 403,
      headers: {
        ...NO_STORE_HEADERS,
        "Referrer-Policy": "no-referrer",
      },
    },
  );
}

function sessionVerificationKey(token: string) {
  return createHash("sha256").update(token).digest("hex");
}

function pruneSessionVerificationBuckets(now: number) {
  for (const [key, bucket] of sessionVerificationBuckets) {
    if (bucket.resetAt <= now) {
      sessionVerificationBuckets.delete(key);
    }
  }
}

function ensureSessionVerificationBucketCapacity(key: string) {
  if (
    sessionVerificationBuckets.has(key) ||
    sessionVerificationBuckets.size < SESSION_VERIFICATION_RATE_LIMIT_MAX_BUCKETS
  ) {
    return;
  }

  const oldestKey = sessionVerificationBuckets.keys().next().value;
  if (oldestKey) {
    sessionVerificationBuckets.delete(oldestKey);
  }
}

function recordSessionVerificationAttempt(token: string):
  | { limited: false }
  | { limited: true; retryAfterSeconds: number } {
  const now = Date.now();
  pruneSessionVerificationBuckets(now);

  const key = sessionVerificationKey(token);
  const bucket = sessionVerificationBuckets.get(key);
  if (bucket && bucket.count >= SESSION_VERIFICATION_RATE_LIMIT_MAX_ATTEMPTS) {
    return {
      limited: true,
      retryAfterSeconds: Math.max(1, Math.ceil((bucket.resetAt - now) / 1000)),
    };
  }

  ensureSessionVerificationBucketCapacity(key);
  const nextBucket =
    bucket && bucket.resetAt > now
      ? { count: bucket.count + 1, resetAt: bucket.resetAt }
      : {
          count: 1,
          resetAt: now + SESSION_VERIFICATION_RATE_LIMIT_WINDOW_MS,
        };
  sessionVerificationBuckets.set(key, nextBucket);
  return { limited: false };
}

function sessionRateLimitedResponse(retryAfterSeconds: number) {
  return NextResponse.json(
    { error_code: "session_verification_rate_limited" },
    {
      status: 429,
      headers: {
        ...NO_STORE_HEADERS,
        "Retry-After": String(retryAfterSeconds),
        "X-RateLimit-Limit": String(SESSION_VERIFICATION_RATE_LIMIT_MAX_ATTEMPTS),
        "X-RateLimit-Remaining": "0",
      },
    },
  );
}

type BackendSessionResponse = {
  user_id?: unknown;
  organization_id?: unknown;
  workspace_id?: unknown;
};

function stringClaim(value: unknown) {
  return typeof value === "string" ? value.trim() || null : null;
}

function claimsFromBackendSession(body: BackendSessionResponse): SessionClaims | null {
  const userId = stringClaim(body.user_id);
  const organizationId = stringClaim(body.organization_id);
  const workspaceId = stringClaim(body.workspace_id);
  if (!userId || !organizationId || !workspaceId) return null;
  return {
    userId,
    organizationId,
    workspaceId,
  };
}

async function verifySessionToken(token: string): Promise<SessionClaims | null> {
  const target = backendApiBaseUrl();
  target.pathname = "/api/auth/session";
  target.search = "";

  try {
    const response = await fetch(target, {
      method: "GET",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
      },
      cache: "no-store",
    });
    if (!response.ok) return null;

    const body = (await response.json()) as BackendSessionResponse;
    return claimsFromBackendSession(body);
  } catch {
    return null;
  }
}

function sessionJson(claims: SessionClaims | null) {
  if (!claims) {
    return {
      authenticated: false,
      claims: ANONYMOUS_SESSION_CLAIMS,
    };
  }
  return {
    authenticated: true,
    claims,
  };
}

export async function GET(request: NextRequest) {
  const token = normalizeSessionToken(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  const claims = token ? await verifySessionToken(token) : null;
  return NextResponse.json(sessionJson(claims), { headers: NO_STORE_HEADERS });
}

export async function POST(request: NextRequest) {
  if (!sameOriginStateChangingRequest(request)) {
    return csrfRejectedResponse();
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error_code: "invalid_session_request" },
      { status: 400, headers: NO_STORE_HEADERS },
    );
  }

  const accessToken = normalizeSessionToken(
    body && typeof body === "object"
      ? (body as { access_token?: unknown }).access_token
      : null,
  );
  if (!accessToken) {
    return NextResponse.json(
      { error_code: "invalid_session_token" },
      { status: 400, headers: NO_STORE_HEADERS },
    );
  }
  const rateLimit = recordSessionVerificationAttempt(accessToken);
  if (rateLimit.limited) {
    return sessionRateLimitedResponse(rateLimit.retryAfterSeconds);
  }

  const claims = await verifySessionToken(accessToken);
  if (!claims) {
    return NextResponse.json(
      { error_code: "invalid_session_token" },
      { status: 401, headers: NO_STORE_HEADERS },
    );
  }

  const response = NextResponse.json(sessionJson(claims), {
    headers: NO_STORE_HEADERS,
  });
  // Do not promote an existing browser cookie; install only the backend-verified
  // bearer session supplied in this request, replacing any previous session id.
  response.cookies.set(buildSessionCookieOptions(accessToken));
  return response;
}

export async function DELETE(request: NextRequest) {
  if (!sameOriginStateChangingRequest(request)) {
    return csrfRejectedResponse();
  }

  const response = NextResponse.json(sessionJson(null), { headers: NO_STORE_HEADERS });
  response.cookies.set(buildExpiredSessionCookieOptions());
  return response;
}
