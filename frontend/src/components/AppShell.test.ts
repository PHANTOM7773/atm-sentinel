import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deriveServiceHealth, resolveTheme, serviceHealthDetail, SessionIndicator, ServiceHealthIndicator, AppShell, THEME_STORAGE_KEY } from "./AppShell";
import type { SystemStatus } from "../lib/types";

const status: SystemStatus = {
  app: "ATM Sentinel",
  version: "0.1.0",
  counts: {},
  dependencies: { ffmpeg: true, ffprobe: true, opencv: true },
  tool_versions: {},
  quality_score_limitations: "Quality scores describe image usability only.",
  recent_activity: [],
  disclaimer: "Prototype evidence organization and integrity tracking.",
};

function render(node: Parameters<typeof renderToStaticMarkup>[0]): string {
  return renderToStaticMarkup(createElement(MemoryRouter, { initialEntries: ["/"] }, node));
}

const originalTheme = document.documentElement.dataset.theme;
const originalLocalStorage = Object.getOwnPropertyDescriptor(window, "localStorage");
const memoryStorage = {
  getItem: (key: string) => memoryStorageValues.get(key) ?? null,
  setItem: (key: string, value: string) => { memoryStorageValues.set(key, String(value)); },
  removeItem: (key: string) => { memoryStorageValues.delete(key); },
  clear: () => { memoryStorageValues.clear(); },
  key: (index: number) => Array.from(memoryStorageValues.keys())[index] ?? null,
  get length() { return memoryStorageValues.size; },
};
const memoryStorageValues = new Map<string, string>();

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  Object.defineProperty(window, "localStorage", { value: memoryStorage, configurable: true });
  vi.stubGlobal("localStorage", memoryStorage);
  memoryStorage.clear();
  delete document.documentElement.dataset.theme;
  document.documentElement.style.removeProperty("color-scheme");
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const path = String(input);
    const body = path.includes("/api/cv/status") ? {} : path.includes("/api/session") ? { mode: "open" } : status;
    return new Response(JSON.stringify(body), {
      status: 200,
      statusText: "OK",
      headers: { "Content-Type": "application/json" },
    });
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  if (originalLocalStorage) Object.defineProperty(window, "localStorage", originalLocalStorage);
  else Reflect.deleteProperty(window, "localStorage");
  if (originalTheme === undefined) delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = originalTheme;
});

describe("AppShell status and session clarity", () => {
  it("derives health only from a successful status response", () => {
    expect(deriveServiceHealth(null, "", true)).toBe("loading");
    expect(deriveServiceHealth(status, "offline", false)).toBe("error");
    expect(deriveServiceHealth({ ...status, dependencies: { ffmpeg: true, ffprobe: false } }, "", false)).toBe("degraded");
    expect(deriveServiceHealth({ ...status, dependencies: {} }, "", false)).toBe("degraded");
    expect(deriveServiceHealth(status, "", false)).toBe("healthy");
  });

  it("describes health without claiming CV model or index verification", () => {
    const detail = serviceHealthDetail("healthy", status);
    expect(detail).toContain("Status endpoint reachable");
    expect(detail).not.toContain("model");
    expect(detail).not.toContain("index");
  });

  it("renders loading, healthy, degraded, and error health states", () => {
    const loading = renderToStaticMarkup(createElement(ServiceHealthIndicator, {
      state: "loading",
      detail: "Checking the local status endpoint",
      refreshing: false,
      onRefresh: () => {},
    }));
    const healthy = renderToStaticMarkup(createElement(ServiceHealthIndicator, {
      state: "healthy",
      detail: "Status endpoint reachable",
      refreshing: false,
      onRefresh: () => {},
    }));
    const degraded = renderToStaticMarkup(createElement(ServiceHealthIndicator, {
      state: "degraded",
      detail: "missing dependencies",
      refreshing: false,
      onRefresh: () => {},
    }));
    const error = renderToStaticMarkup(createElement(ServiceHealthIndicator, {
      state: "error",
      detail: "Status endpoint did not respond successfully",
      refreshing: false,
      onRefresh: () => {},
    }));
    expect(loading).toContain("Checking status");
    expect(loading).not.toContain("bg-ok");
    expect(healthy).toContain("Service available");
    expect(healthy).toContain("bg-ok");
    expect(degraded).toContain("Service degraded");
    expect(error).toContain("Service unavailable");
  });

  it("does not claim protected access until the backend confirms it", () => {
    const unknown = renderToStaticMarkup(createElement(SessionIndicator, { session: null, error: null, onOpen: () => {} }));
    const required = renderToStaticMarkup(createElement(SessionIndicator, {
      session: { mode: "secured", protectedAccess: false },
      error: null,
      onOpen: () => {},
    }));
    const confirmed = renderToStaticMarkup(createElement(SessionIndicator, {
      session: { mode: "secured", protectedAccess: true },
      error: null,
      onOpen: () => {},
    }));
    const failed = renderToStaticMarkup(createElement(SessionIndicator, {
      session: null,
      error: "backend unavailable",
      onOpen: () => {},
    }));
    expect(unknown).toContain("Session unknown");
    expect(required).toContain("Passphrase required");
    expect(confirmed).toContain("Protected access confirmed");
    expect(failed).toContain("Session check failed");
  });

  it("starts with neutral health and session states before effects run", () => {
    const html = render(createElement(AppShell, null, createElement("div")));
    expect(html).toContain("Checking status");
    expect(html).toContain("Session unknown");
    expect(html).not.toContain("Service available");
    expect(html).not.toContain("Local service");
    expect(html).toContain("never identity conclusions");
  });

  it("resolves stored theme before OS preference", () => {
    expect(resolveTheme(null, false)).toBe("light");
    expect(resolveTheme(null, true)).toBe("dark");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
    expect(resolveTheme("invalid", true)).toBe("dark");
  });

  it("renders an accessible light and dark toggle", () => {
    const html = render(createElement(AppShell, null, createElement("div")));
    expect(html).toContain('aria-label="Switch to dark mode"');
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain(">Dark</button>");
  });

  it("applies and persists light and dark mode", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(createElement(MemoryRouter, { initialEntries: ["/"] }, createElement(AppShell, null, createElement("div"))));
    });

    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
    const darkToggle = container.querySelector('[aria-label="Switch to dark mode"]') as HTMLButtonElement;
    expect(darkToggle).toBeTruthy();

    await act(async () => {
      darkToggle.click();
    });

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(resolveTheme(localStorage.getItem(THEME_STORAGE_KEY), false)).toBe("dark");
    expect(container.querySelector('[aria-label="Switch to light mode"]')).toBeTruthy();

    const lightToggle = container.querySelector('[aria-label="Switch to light mode"]') as HTMLButtonElement;
    await act(async () => {
      lightToggle.click();
    });

    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });
});
