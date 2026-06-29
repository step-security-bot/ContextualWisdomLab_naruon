/* @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getWorkspaceStartupView,
  setWorkspaceStartupView,
  subscribeWorkspaceStartupView,
} from "./workspace-preferences";

describe("workspace startup preferences", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("returns dashboard when localStorage is empty", () => {
    expect(getWorkspaceStartupView()).toBe("dashboard");
  });

  it("returns the stored valid view when available", () => {
    localStorage.setItem("naruon_startup_view", "email");
    expect(getWorkspaceStartupView()).toBe("email");
  });

  it("returns dashboard when localStorage contains an invalid value", () => {
    localStorage.setItem("naruon_startup_view", "invalid_view");
    expect(getWorkspaceStartupView()).toBe("dashboard");
  });

  it("falls back to dashboard when localStorage reads throw", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(getWorkspaceStartupView()).toBe("dashboard");
  });

  it("stores the value in localStorage and dispatches a CustomEvent", () => {
    const listener = vi.fn();
    window.addEventListener("naruon:startup-view-change", listener);

    setWorkspaceStartupView("calendar");

    expect(localStorage.getItem("naruon_startup_view")).toBe("calendar");
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener.mock.calls[0][0].detail).toEqual({ view: "calendar" });

    window.removeEventListener("naruon:startup-view-change", listener);
  });

  it("does not throw or skip notification when localStorage writes throw", () => {
    const listener = vi.fn();
    window.addEventListener("naruon:startup-view-change", listener);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(() => setWorkspaceStartupView("calendar")).not.toThrow();
    expect(listener).toHaveBeenCalledTimes(1);

    window.removeEventListener("naruon:startup-view-change", listener);
  });

  it("subscribes to and cleans up custom and storage events correctly", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeWorkspaceStartupView(listener);

    // Test custom event
    window.dispatchEvent(new CustomEvent("naruon:startup-view-change", { detail: { view: "email" } }));
    expect(listener).toHaveBeenCalledTimes(1);

    // Test unrelated storage event
    const unrelatedStorageEvent = new Event("storage") as StorageEvent;
    Object.defineProperty(unrelatedStorageEvent, "key", { value: "some_other_key", configurable: true });
    window.dispatchEvent(unrelatedStorageEvent);
    expect(listener).toHaveBeenCalledTimes(1);

    // Test related storage event
    const relatedStorageEvent = new Event("storage") as StorageEvent;
    Object.defineProperty(relatedStorageEvent, "key", { value: "naruon_startup_view", configurable: true });
    window.dispatchEvent(relatedStorageEvent);
    expect(listener).toHaveBeenCalledTimes(2);

    // Test unsubscribe
    unsubscribe();
    window.dispatchEvent(new CustomEvent("naruon:startup-view-change", { detail: { view: "calendar" } }));
    const unsubscribedStorageEvent = new Event("storage") as StorageEvent;
    Object.defineProperty(unsubscribedStorageEvent, "key", { value: "naruon_startup_view", configurable: true });
    window.dispatchEvent(unsubscribedStorageEvent);
    expect(listener).toHaveBeenCalledTimes(2); // Should not increase
  });
});
