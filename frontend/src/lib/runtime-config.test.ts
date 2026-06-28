import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RuntimeConfig } from "./runtime-config";

describe("fetchRuntimeConfig", () => {
  let fetchRuntimeConfig: typeof import("./runtime-config").fetchRuntimeConfig;

  beforeEach(async () => {
    vi.resetModules();
    const runtimeConfigModule = await import("./runtime-config");
    fetchRuntimeConfig = runtimeConfigModule.fetchRuntimeConfig;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const mockConfig: RuntimeConfig = {
    product_name: "TestProduct",
    version: "1.0.0",
    features: { test_feature: true },
  };

  const fallbackConfig: RuntimeConfig = {
    product_name: "Naruon",
    version: "fallback",
    features: {},
  };

  it("fetches runtime config without baseUrl and caches the result", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockConfig,
    });
    vi.stubGlobal("fetch", fetchMock);

    const config = await fetchRuntimeConfig();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/runtime-config");
    expect(config).toEqual(mockConfig);
  });

  it("fetches runtime config with baseUrl", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockConfig,
    });
    vi.stubGlobal("fetch", fetchMock);

    const config = await fetchRuntimeConfig("https://example.com");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("https://example.com/api/runtime-config");
    expect(config).toEqual(mockConfig);
  });

  it("returns cached config on subsequent calls without fetching again", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockConfig,
    });
    vi.stubGlobal("fetch", fetchMock);

    const config1 = await fetchRuntimeConfig();
    const config2 = await fetchRuntimeConfig();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(config1).toEqual(mockConfig);
    expect(config2).toEqual(mockConfig);
  });

  it("returns the in-flight promise if a fetch is already in progress", async () => {
    let resolveJson: (value: RuntimeConfig) => void;
    const jsonPromise = new Promise<RuntimeConfig>((resolve) => {
      resolveJson = resolve;
    });

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => jsonPromise,
    });
    vi.stubGlobal("fetch", fetchMock);

    const promise1 = fetchRuntimeConfig();
    const promise2 = fetchRuntimeConfig();

    expect(fetchMock).toHaveBeenCalledTimes(1);

    resolveJson!(mockConfig);

    const [config1, config2] = await Promise.all([promise1, promise2]);

    expect(config1).toEqual(mockConfig);
    expect(config2).toEqual(mockConfig);
  });

  it("returns fallback config when fetch response is not ok", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
    });
    vi.stubGlobal("fetch", fetchMock);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const config = await fetchRuntimeConfig();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(consoleErrorSpy).toHaveBeenCalledWith("Runtime config fetch failed, using fallback", {
      error_type: "Error",
    });
    expect(config).toEqual(fallbackConfig);
  });

  it("returns fallback config when fetch throws a network error", async () => {
    const networkError = new Error("Network Error");
    const fetchMock = vi.fn().mockRejectedValue(networkError);
    vi.stubGlobal("fetch", fetchMock);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const config = await fetchRuntimeConfig();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(consoleErrorSpy).toHaveBeenCalledWith("Runtime config fetch failed, using fallback", {
      error_type: "Error",
    });
    const loggedArgs = consoleErrorSpy.mock.calls[0] ?? [];
    expect(loggedArgs).not.toContain(networkError);
    expect(JSON.stringify(loggedArgs)).not.toContain("Network Error");
    expect(config).toEqual(fallbackConfig);
  });

  it("returns fallback config and logs string error type correctly", async () => {
    const fetchMock = vi.fn().mockRejectedValue("String Error");
    vi.stubGlobal("fetch", fetchMock);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const config = await fetchRuntimeConfig();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(consoleErrorSpy).toHaveBeenCalledWith("Runtime config fetch failed, using fallback", {
      error_type: "string",
    });
    expect(config).toEqual(fallbackConfig);
  });

  it("returns fallback config and logs custom error name correctly", async () => {
    class CustomError extends Error {
      constructor(message: string) {
        super(message);
        this.name = "MyCustomError";
      }
    }
    const fetchMock = vi.fn().mockRejectedValue(new CustomError("Custom error message"));
    vi.stubGlobal("fetch", fetchMock);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const config = await fetchRuntimeConfig();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(consoleErrorSpy).toHaveBeenCalledWith("Runtime config fetch failed, using fallback", {
      error_type: "MyCustomError",
    });
    expect(config).toEqual(fallbackConfig);
  });

  it("returns fallback config and logs default Error type for error without name", async () => {
    const unnamedError = new Error("Unnamed");
    unnamedError.name = "";
    const fetchMock = vi.fn().mockRejectedValue(unnamedError);
    vi.stubGlobal("fetch", fetchMock);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const config = await fetchRuntimeConfig();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(consoleErrorSpy).toHaveBeenCalledWith("Runtime config fetch failed, using fallback", {
      error_type: "Error",
    });
    expect(config).toEqual(fallbackConfig);
  });

  it("returns fallback config and logs object error type for null correctly", async () => {
    const fetchMock = vi.fn().mockRejectedValue(null);
    vi.stubGlobal("fetch", fetchMock);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const config = await fetchRuntimeConfig();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(consoleErrorSpy).toHaveBeenCalledWith("Runtime config fetch failed, using fallback", {
      error_type: "object",
    });
    expect(config).toEqual(fallbackConfig);
  });

  it("returns fallback config and logs object error type for generic objects", async () => {
    const fetchMock = vi.fn().mockRejectedValue({});
    vi.stubGlobal("fetch", fetchMock);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const config = await fetchRuntimeConfig();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(consoleErrorSpy).toHaveBeenCalledWith("Runtime config fetch failed, using fallback", {
      error_type: "object",
    });
    expect(config).toEqual(fallbackConfig);
  });
});
