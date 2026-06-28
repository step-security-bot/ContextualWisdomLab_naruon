/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// We'll mock the hook to get access to its inputs, since we can't easily
// mock react's named exports without issues with CJS/ESM in this setup
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let useSyncExternalStoreArgs: any[] = [];

vi.mock("react", async () => {
  const actualReact = await vi.importActual("react");
  return {
    ...actualReact,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    useSyncExternalStore: vi.fn((...args: any[]) => {
      useSyncExternalStoreArgs = args;
      return args[1](); // Call getSnapshot by default
    }),
  };
});

import {
  setMobileWorkspaceView,
  useMobileWorkspaceView,
} from "./mobile-workspace";

describe("mobile-workspace", () => {
  beforeEach(() => {
    delete window.__naruonMobileWorkspace;
    window.location.hash = "";
    useSyncExternalStoreArgs = [];
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("setMobileWorkspaceView", () => {
    it("updates the view and dispatches events", () => {
      const pushStateSpy = vi.spyOn(window.history, "pushState");
      const dispatchEventSpy = vi.spyOn(window, "dispatchEvent");

      setMobileWorkspaceView("detail");

      expect(window.__naruonMobileWorkspace?.view).toBe("detail");
      expect(pushStateSpy).toHaveBeenCalledWith(null, "", "#mobile-detail");

      expect(dispatchEventSpy).toHaveBeenCalled();
      const event = dispatchEventSpy.mock.calls[0][0] as CustomEvent;
      expect(event.type).toBe("naruon:mobile-workspace");
      expect(event.detail).toEqual({ view: "detail" });
    });

    it("does not update hash when updateHash is false", () => {
      const pushStateSpy = vi.spyOn(window.history, "pushState");

      setMobileWorkspaceView("actions", { updateHash: false });

      expect(window.__naruonMobileWorkspace?.view).toBe("actions");
      expect(pushStateSpy).not.toHaveBeenCalled();
    });

    it("notifies listeners when the view changes", () => {
      const listener = vi.fn();

      window.__naruonMobileWorkspace = {
        view: "inbox",
        listeners: new Set([listener]),
      };

      setMobileWorkspaceView("calendar");

      expect(listener).toHaveBeenCalled();
      expect(window.__naruonMobileWorkspace.view).toBe("calendar");
    });
  });

  describe("useMobileWorkspaceView", () => {
    it("sets up useSyncExternalStore with correct subscribe and snapshot functions", () => {
      // Call the hook so our mock gets invoked
      const result = useMobileWorkspaceView();

      // Initially hash is empty, so it falls back to inbox
      expect(result).toBe("inbox");

      expect(useSyncExternalStoreArgs).toHaveLength(3);
      const [subscribe, getSnapshot, getServerSnapshot] =
        useSyncExternalStoreArgs;

      // Test getServerSnapshot
      expect(getServerSnapshot()).toBe("inbox");

      // Test getSnapshot logic - default
      expect(getSnapshot()).toBe("inbox");

      // Test getSnapshot with valid hash
      window.location.hash = "#mobile-search";
      expect(getSnapshot()).toBe("search");

      // Test getSnapshot with invalid hash - falls back to store
      window.location.hash = "#mobile-invalid";
      expect(getSnapshot()).toBe("inbox");

      window.__naruonMobileWorkspace = {
        view: "detail",
        listeners: new Set(),
      };
      expect(getSnapshot()).toBe("detail");

      // Test subscribe function
      const listener = vi.fn();
      const addEventListenerSpy = vi.spyOn(window, "addEventListener");
      const removeEventListenerSpy = vi.spyOn(window, "removeEventListener");

      const unsubscribe = subscribe(listener);

      expect(addEventListenerSpy).toHaveBeenCalledWith("hashchange", listener);
      expect(window.__naruonMobileWorkspace.listeners.has(listener)).toBe(true);

      unsubscribe();

      expect(removeEventListenerSpy).toHaveBeenCalledWith(
        "hashchange",
        listener,
      );
      expect(window.__naruonMobileWorkspace.listeners.has(listener)).toBe(
        false,
      );
    });
  });

  describe("server-side rendering simulation", () => {
    beforeEach(() => {
      vi.stubGlobal("window", undefined);
      useSyncExternalStoreArgs = [];
    });

    afterEach(() => {
      setMobileWorkspaceView("inbox", { updateHash: false });
      vi.unstubAllGlobals();
    });

    it("keeps server-side view updates in the server store", () => {
      expect(() => setMobileWorkspaceView("calendar")).not.toThrow();

      expect(useMobileWorkspaceView()).toBe("calendar");

      expect(useSyncExternalStoreArgs).toHaveLength(3);
      const [, getSnapshot, getServerSnapshot] = useSyncExternalStoreArgs;
      expect(getSnapshot()).toBe("calendar");
      expect(getServerSnapshot()).toBe("inbox");
    });

    it("uses the inbox fallback for a fresh server render", () => {
      expect(useMobileWorkspaceView()).toBe("inbox");

      expect(useSyncExternalStoreArgs).toHaveLength(3);
      const [, getSnapshot, getServerSnapshot] = useSyncExternalStoreArgs;
      expect(getSnapshot()).toBe("inbox");
      expect(getServerSnapshot()).toBe("inbox");
    });
  });
});
