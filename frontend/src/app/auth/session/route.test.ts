import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DELETE, GET, POST } from "./route";

const ORIGINAL_ENV = { ...process.env };

function base64UrlJson(body: unknown) {
  return Buffer.from(JSON.stringify(body)).toString("base64url");
}

function signedFixtureToken(payload: Record<string, unknown>) {
  return `${base64UrlJson({ alg: "HS256", typ: "JWT" })}.${base64UrlJson(payload)}.signature`;
}

function verifiedSessionResponse() {
  return Response.json({
    user_id: "user-1",
    organization_id: "org-acme",
    workspace_id: "workspace-acme",
  });
}

describe("/auth/session route", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    process.env = { ...ORIGINAL_ENV };
    vi.stubEnv("BACKEND_INTERNAL_URL", "https://api.naruon.net");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    process.env = { ...ORIGINAL_ENV };
  });

  it("stores the bearer token in an HttpOnly secure same-site cookie", async () => {
    const token = signedFixtureToken({
      sub: "user-1",
      org: "org-acme",
      workspace: "workspace-acme",
      exp: Math.floor(Date.now() / 1000) + 300,
    });
    const fetchMock = vi.fn(async (input: URL | RequestInfo, init?: RequestInit) => {
      expect(String(input)).toBe("https://api.naruon.net/api/auth/session");
      expect(new Headers(init?.headers).get("authorization")).toBe(`Bearer ${token}`);
      return verifiedSessionResponse();
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new NextRequest("https://app.naruon.net/auth/session", {
        method: "POST",
        headers: {
          Origin: "https://app.naruon.net",
          Cookie: "naruon_session=attacker-fixed-session",
        },
        body: JSON.stringify({ access_token: token }),
      }),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual({
      authenticated: true,
      claims: {
        userId: "user-1",
        organizationId: "org-acme",
        workspaceId: "workspace-acme",
      },
    });
    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("naruon_session=");
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("Secure");
    expect(setCookie).toContain("SameSite=lax");
    expect(setCookie).toContain("Max-Age=43200");
    expect(setCookie).not.toContain("access_token");
    expect(setCookie).not.toContain("attacker-fixed-session");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("stores a session when browser origin matches the forwarded host", async () => {
    const token = signedFixtureToken({
      sub: "user-1",
      org: "org-acme",
      workspace: "workspace-acme",
      exp: Math.floor(Date.now() / 1000) + 300,
    });
    const fetchMock = vi.fn(async () => verifiedSessionResponse());
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new NextRequest("http://internal-frontend:3000/auth/session", {
        method: "POST",
        headers: {
          Host: "127.0.0.1:3000",
          Origin: "http://127.0.0.1:3000",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ access_token: token }),
      }),
    );

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      authenticated: true,
      claims: {
        userId: "user-1",
        organizationId: "org-acme",
        workspaceId: "workspace-acme",
      },
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("returns public claims without exposing the cookie value", async () => {
    const token = signedFixtureToken({
      sub: "user-2",
      org: "org-beta",
      workspace: "workspace-beta",
    });
    const fetchMock = vi.fn(async (input: URL | RequestInfo, init?: RequestInit) => {
      expect(String(input)).toBe("https://api.naruon.net/api/auth/session");
      expect(new Headers(init?.headers).get("authorization")).toBe(`Bearer ${token}`);
      return Response.json({
        user_id: "user-2",
        organization_id: "org-beta",
        workspace_id: "workspace-beta",
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest("https://app.naruon.net/auth/session", {
      headers: { Origin: "https://app.naruon.net", Cookie: `naruon_session=${token}` },
    });

    const response = await GET(request);

    await expect(response.json()).resolves.toEqual({
      authenticated: true,
      claims: {
        userId: "user-2",
        organizationId: "org-beta",
        workspaceId: "workspace-beta",
      },
    });
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects forged tokens that the backend verifier does not accept", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(
      { detail: "Authentication required" },
      { status: 401 },
    )));
    const forgedToken = signedFixtureToken({
      sub: "attacker",
      org: "org-victim",
      workspace: "workspace-victim",
      exp: Math.floor(Date.now() / 1000) + 300,
    });

    const response = await POST(new NextRequest("https://app.naruon.net/auth/session", {
      method: "POST",
      headers: { Origin: "https://app.naruon.net" },
      body: JSON.stringify({ access_token: forgedToken }),
    }));

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({
      error_code: "invalid_session_token",
    });
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it.each([
    [
      "user",
      {
        organization_id: "org-acme",
        workspace_id: "workspace-acme",
      },
    ],
    [
      "organization",
      {
        user_id: "user-1",
        workspace_id: "workspace-acme",
      },
    ],
    [
      "workspace",
      {
        user_id: "user-1",
        organization_id: "org-acme",
      },
    ],
  ])("rejects backend session responses without %s scope", async (_scope, body) => {
    const token = signedFixtureToken({
      sub: "user-1",
      org: "org-acme",
      workspace: "workspace-acme",
      exp: Math.floor(Date.now() / 1000) + 300,
    });
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(body)));

    const response = await POST(new NextRequest("https://app.naruon.net/auth/session", {
      method: "POST",
      headers: { Origin: "https://app.naruon.net" },
      body: JSON.stringify({ access_token: token }),
    }));

    expect(response.status).toBe(401);
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual({
      error_code: "invalid_session_token",
    });
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("rejects non-JWT session token formats before backend verification", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(new NextRequest("https://app.naruon.net/auth/session", {
      method: "POST",
      headers: { Origin: "https://app.naruon.net" },
      body: JSON.stringify({ access_token: "<script>alert(1)</script>" }),
    }));

    expect(response.status).toBe(400);
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual({
      error_code: "invalid_session_token",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rate limits repeated session verification attempts before backend fanout", async () => {
    const token = signedFixtureToken({
      sub: "rate-limited-user",
      org: "org-acme",
      workspace: "workspace-acme",
      exp: Math.floor(Date.now() / 1000) + 300,
    });
    const fetchMock = vi.fn(async () => verifiedSessionResponse());
    vi.stubGlobal("fetch", fetchMock);

    for (let attempt = 0; attempt < 10; attempt += 1) {
      const response = await POST(new NextRequest("https://app.naruon.net/auth/session", {
        method: "POST",
        headers: { Origin: "https://app.naruon.net" },
        body: JSON.stringify({ access_token: token }),
      }));

      expect(response.status).toBe(200);
    }

    const response = await POST(new NextRequest("https://app.naruon.net/auth/session", {
      method: "POST",
      headers: { Origin: "https://app.naruon.net" },
      body: JSON.stringify({ access_token: token }),
    }));

    expect(response.status).toBe(429);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("retry-after")).toMatch(/^[1-9][0-9]*$/);
    await expect(response.json()).resolves.toEqual({
      error_code: "session_verification_rate_limited",
    });
    expect(fetchMock).toHaveBeenCalledTimes(10);
  });

  it("rejects cross-site session persistence before backend verification", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(new NextRequest("https://app.naruon.net/auth/session", {
      method: "POST",
      headers: {
        Origin: "https://evil.example",
      },
      body: JSON.stringify({ access_token: "attacker.jwt.token" }),
    }));

    expect(response.status).toBe(403);
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
    await expect(response.json()).resolves.toEqual({
      error_code: "csrf_origin_rejected",
      message: "Cross-site session updates are not allowed",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects state changing requests if both origin and referer are absent", async () => {
    const token = signedFixtureToken({ sub: "user-1", org: "org-acme" });

    const response = await POST(new NextRequest("https://app.naruon.net/auth/session", {
      method: "POST",
      body: JSON.stringify({ access_token: token }),
    }));

    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({
      error_code: "csrf_origin_rejected",
      message: "Cross-site session updates are not allowed",
    });
  });

  it("accepts state changing requests if origin is missing but valid referer is present", async () => {
    const token = signedFixtureToken({ sub: "user-1", org: "org-acme", workspace: "workspace-acme", exp: Math.floor(Date.now() / 1000) + 300 });
    vi.stubGlobal("fetch", vi.fn(async () => verifiedSessionResponse()));

    const response = await POST(new NextRequest("https://app.naruon.net/auth/session", {
      method: "POST",
      headers: {
        Referer: "https://app.naruon.net/dashboard",
        Cookie: "naruon_session=attacker-fixed-session",
      },
      body: JSON.stringify({ access_token: token }),
    }));

    expect(response.status).toBe(200);
  });

  it("rejects state changing requests if origin is missing and referer has invalid URL", async () => {
    const token = signedFixtureToken({ sub: "user-1", org: "org-acme" });

    const response = await POST(new NextRequest("https://app.naruon.net/auth/session", {
      method: "POST",
      headers: { Referer: "invalid-url" },
      body: JSON.stringify({ access_token: token }),
    }));

    expect(response.status).toBe(403);
  });

  it("expires the session cookie on logout", async () => {
    const response = await DELETE(new NextRequest("https://app.naruon.net/auth/session", {
      method: "DELETE",
      headers: { Origin: "https://app.naruon.net" },
    }));

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("naruon_session=");
    expect(setCookie).toContain("Max-Age=0");
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("Secure");
    expect(setCookie).toContain("SameSite=lax");
  });
});
