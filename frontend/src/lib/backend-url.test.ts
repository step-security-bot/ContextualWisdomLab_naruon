import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { backendApiBaseUrl, parseBackendInternalUrl } from "./backend-url";

const ORIGINAL_ENV = { ...process.env };

describe("backend URL guard", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    process.env = { ...ORIGINAL_ENV };
    delete process.env.BACKEND_INTERNAL_URL;
    delete process.env.ALLOW_DOCKER_BACKEND_INTERNAL_URL;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    process.env = { ...ORIGINAL_ENV };
  });

  it("accepts public HTTPS backend origins", () => {
    expect(parseBackendInternalUrl("https://api.naruon.net").origin).toBe(
      "https://api.naruon.net",
    );
  });

  it("rejects private IPv4 and IPv4-mapped IPv6 backend origins", () => {
    for (const url of [
      "https://127.0.0.1",
      "https://10.0.0.4",
      "https://192.168.1.10",
      "https://172.16.0.9",
      "https://169.254.169.254",
      "https://[::ffff:127.0.0.1]",
      "https://[::ffff:10.0.0.1]",
      "https://[::ffff:192.168.0.1]",
      "https://[::ffff:172.16.0.1]",
      "https://[::ffff:169.254.1.1]",
    ]) {
      expect(() => parseBackendInternalUrl(url), url).toThrow(
        "private/loopback/link-local",
      );
    }
  });

  it("allows exact Docker internal backend URLs only with the explicit opt-in", () => {
    expect(() => parseBackendInternalUrl("http://backend:8000")).toThrow(
      "https://",
    );
    expect(() => parseBackendInternalUrl("http://127.0.0.1:8000")).toThrow(
      "https://",
    );
    process.env.ALLOW_DOCKER_BACKEND_INTERNAL_URL = "1";
    expect(parseBackendInternalUrl("http://backend:8000").origin).toBe(
      "http://backend:8000",
    );
    expect(parseBackendInternalUrl("http://127.0.0.1:8000").origin).toBe(
      "http://127.0.0.1:8000",
    );
    expect(parseBackendInternalUrl("http://localhost:8000").origin).toBe(
      "http://localhost:8000",
    );
    expect(() => parseBackendInternalUrl("http://127.0.0.1:8001")).toThrow(
      "https://",
    );
  });

  it("rejects invalid URL strings", () => {
    expect(() => parseBackendInternalUrl("not-a-valid-url")).toThrow(
      "BACKEND_INTERNAL_URL is not a valid URL",
    );
  });

  it("rejects non-HTTPS URLs in normal mode", () => {
    expect(() => parseBackendInternalUrl("http://api.naruon.net")).toThrow(
      "must use https:// in split deployments",
    );
  });

  it("rejects URLs without a hostname", () => {
    // A mock URL object with protocol "https:" but empty hostname
    // since Node.js newer URL parser rejects `https:///` and similar.
    const originalURL = global.URL;
    try {
      const MockURL = class extends URL {
        constructor(input: string | URL, base?: string | URL) {
          super(input, base);
          if (input === "https:///empty") {
            Object.defineProperty(this, "hostname", { get: () => "" });
          }
        }
      };
      global.URL = MockURL as unknown as typeof URL;
      expect(() => parseBackendInternalUrl("https:///empty")).toThrow(
        "BACKEND_INTERNAL_URL must include a hostname",
      );
    } finally {
      global.URL = originalURL;
    }
  });

  it("uses the environment variable when provided", () => {
    vi.stubEnv("BACKEND_INTERNAL_URL", "https://backend.example.com");
    expect(backendApiBaseUrl().origin).toBe("https://backend.example.com");
  });

  it("falls back to local backend in development", () => {
    expect(backendApiBaseUrl().origin).toBe("http://127.0.0.1:8000");
  });

  it("requires a runtime backend origin in production", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(() => backendApiBaseUrl()).toThrow("production runtime");
  });
});
