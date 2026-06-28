import { createHash, randomInt } from "node:crypto";

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
const SESSION_VERIFICATION_SOURCE_RATE_LIMIT_MAX_ATTEMPTS = 30;
const SESSION_VERIFICATION_RATE_LIMIT_MAX_BUCKETS = 4096;
const SESSION_VERIFICATION_PRUNE_SCAN_LIMIT = 64;
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
  let scanned = 0;
  for (const [key, bucket] of sessionVerificationBuckets) {
    if (bucket.resetAt <= now) {
      sessionVerificationBuckets.delete(key);
    }
    scanned += 1;
    if (scanned >= SESSION_VERIFICATION_PRUNE_SCAN_LIMIT) break;
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

function sessionVerificationSourceKey(request: NextRequest) {
  const forwardedFor = firstHeaderValue(request.headers.get("x-forwarded-for"));
  const realIp = firstHeaderValue(request.headers.get("x-real-ip"));
  const cloudflareIp = firstHeaderValue(request.headers.get("cf-connecting-ip"));
  const address = [forwardedFor, realIp, cloudflareIp].find(
    (value) => value && !CONTROL_CHARACTER_PATTERN.test(value),
  ) ?? "unknown";
  const userAgent = request.headers.get("user-agent")?.slice(0, 128) ?? "unknown";
  return createHash("sha256").update(`${address}\0${userAgent}`).digest("hex");
}

function recordSessionVerificationAttempt(key: string, maxAttempts: number):
  | { limited: false }
  | { limited: true; retryAfterSeconds: number } {
  const now = Date.now();
  pruneSessionVerificationBuckets(now);

  const bucket = sessionVerificationBuckets.get(key);
  if (bucket && bucket.count >= maxAttempts) {
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

function sessionRateLimitedResponse(retryAfterSeconds: number, maxAttempts: number) {
  return NextResponse.json(
    { error_code: "session_verification_rate_limited" },
    {
      status: 429,
      headers: {
        ...NO_STORE_HEADERS,
        "Retry-After": String(retryAfterSeconds + randomInt(1, 4)),
        "X-RateLimit-Limit": String(maxAttempts),
        "X-RateLimit-Remaining": "0",
      },
    },
  );
}

function setVerifiedSessionCookie(response: NextResponse, token: string) {
  response.cookies.set({
    ...buildSessionCookieOptions(token),
    httpOnly: true,
    secure: true,
    sameSite: "lax",
  });
}

function setExpiredSessionCookie(response: NextResponse) {
  response.cookies.set({
    ...buildExpiredSessionCookieOptions(),
    httpOnly: true,
    secure: true,
    sameSite: "lax",
  });
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
  const tokenRateLimit = recordSessionVerificationAttempt(
    `token:${sessionVerificationKey(accessToken)}`,
    SESSION_VERIFICATION_RATE_LIMIT_MAX_ATTEMPTS,
  );
  if (tokenRateLimit.limited) {
    return sessionRateLimitedResponse(
      tokenRateLimit.retryAfterSeconds,
      SESSION_VERIFICATION_RATE_LIMIT_MAX_ATTEMPTS,
    );
  }

  const sourceRateLimit = recordSessionVerificationAttempt(
    `source:${sessionVerificationSourceKey(request)}`,
    SESSION_VERIFICATION_SOURCE_RATE_LIMIT_MAX_ATTEMPTS,
  );
  if (sourceRateLimit.limited) {
    return sessionRateLimitedResponse(
      sourceRateLimit.retryAfterSeconds,
      SESSION_VERIFICATION_SOURCE_RATE_LIMIT_MAX_ATTEMPTS,
    );
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
  setVerifiedSessionCookie(response, accessToken);
  return response;
}

export async function DELETE(request: NextRequest) {
  if (!sameOriginStateChangingRequest(request)) {
    return csrfRejectedResponse();
  }

  const response = NextResponse.json(sessionJson(null), { headers: NO_STORE_HEADERS });
  setExpiredSessionCookie(response);
  return response;
}
