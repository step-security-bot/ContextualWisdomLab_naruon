import { createHash, randomBytes } from "node:crypto";

export const OIDC_PKCE_COOKIE_NAME = "naruon_oidc_pkce";

export const OIDC_NO_STORE_HEADERS = {
  "Cache-Control": "no-store",
};

const DEFAULT_OIDC_SCOPE = "openid profile email";
const OIDC_COOKIE_MAX_AGE_SECONDS = 10 * 60;
const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001f\u007f]/;

export interface ServerOidcConfig {
  issuerUrl: string;
  clientId: string;
  redirectUri: string;
  scope: string;
  authorizationEndpoint: string;
  tokenEndpoint: string;
}

export interface OidcStateCookiePayload {
  state: string;
  verifier: string;
  return_to: string;
}

function envValue(name: string): string | null {
  const value = process.env[name]?.trim();
  return value ? value : null;
}

function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

export function serverOidcConfig(origin: string): ServerOidcConfig | null {
  const issuerUrl = envValue("NEXT_PUBLIC_OIDC_ISSUER_URL");
  const clientId = envValue("NEXT_PUBLIC_OIDC_CLIENT_ID");
  if (!issuerUrl || !clientId) return null;

  const normalizedIssuer = trimTrailingSlash(issuerUrl);
  const keycloakEndpointBase = `${normalizedIssuer}/protocol/openid-connect`;
  return {
    issuerUrl: normalizedIssuer,
    clientId,
    redirectUri: envValue("NEXT_PUBLIC_OIDC_REDIRECT_URI") ?? `${origin}/auth/callback`,
    scope: envValue("NEXT_PUBLIC_OIDC_SCOPE") ?? DEFAULT_OIDC_SCOPE,
    authorizationEndpoint:
      envValue("NEXT_PUBLIC_OIDC_AUTHORIZATION_ENDPOINT") ?? `${keycloakEndpointBase}/auth`,
    tokenEndpoint:
      envValue("NEXT_PUBLIC_OIDC_TOKEN_ENDPOINT") ?? `${keycloakEndpointBase}/token`,
  };
}

export function safeReturnTo(value: unknown) {
  const candidate = typeof value === "string" ? value.trim() : "";
  if (!candidate) return "/";

  try {
    const decodedCandidate = decodeURIComponent(candidate);
    if (
      !candidate.startsWith("/") ||
      candidate.startsWith("//") ||
      decodedCandidate.startsWith("//") ||
      /[\u0000-\u001f\u007f\\]/.test(candidate) ||
      /[\u0000-\u001f\u007f\\]/.test(decodedCandidate)
    ) {
      return "/";
    }

    const url = new URL(candidate, "http://localhost");
    if (url.origin !== "http://localhost") return "/";

    const safePath = url.pathname + url.search + url.hash;
    const decodedSafePath = decodeURIComponent(safePath);

    if (
      !safePath.startsWith("/") ||
      safePath.startsWith("//") ||
      decodedSafePath.startsWith("//") ||
      /[\u0000-\u001f\u007f\\]/.test(decodedSafePath)
    ) {
      return "/";
    }

    return safePath;
  } catch {
    return "/";
  }
}

export function randomUrlSafeString(byteLength: number) {
  return randomBytes(byteLength).toString("base64url");
}

export function pkceChallenge(verifier: string) {
  return createHash("sha256").update(verifier, "ascii").digest("base64url");
}

export function encodeOidcStateCookie(payload: OidcStateCookiePayload) {
  return Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
}

export function decodeOidcStateCookie(value: string | undefined): OidcStateCookiePayload | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(Buffer.from(value, "base64url").toString("utf8")) as {
      state?: unknown;
      verifier?: unknown;
      return_to?: unknown;
    };
    if (
      typeof parsed.state !== "string" ||
      typeof parsed.verifier !== "string" ||
      typeof parsed.return_to !== "string" ||
      !parsed.state ||
      !parsed.verifier
    ) {
      return null;
    }
    return {
      state: parsed.state,
      verifier: parsed.verifier,
      return_to: safeReturnTo(parsed.return_to),
    };
  } catch {
    return null;
  }
}

export function oidcStateCookieOptions(value: string) {
  return {
    name: OIDC_PKCE_COOKIE_NAME,
    value,
    httpOnly: true,
    secure: true,
    sameSite: "lax" as const,
    path: "/auth",
    maxAge: OIDC_COOKIE_MAX_AGE_SECONDS,
  };
}

export function expiredOidcStateCookieOptions() {
  return {
    name: OIDC_PKCE_COOKIE_NAME,
    value: "",
    httpOnly: true,
    secure: true,
    sameSite: "lax" as const,
    path: "/auth",
    maxAge: 0,
  };
}
