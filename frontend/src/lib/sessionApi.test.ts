import { afterEach, describe, expect, it, vi } from "vitest";
import { sessionApi, systemApi } from "./api";

const BASE = "http://127.0.0.1:8000";

interface FetchCall {
  url: string;
  init?: RequestInit;
}

interface StubResponse {
  body: unknown;
  status?: number;
}

function stubFetchSequence(responses: StubResponse[]): FetchCall[] {
  const calls: FetchCall[] = [];
  let index = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      const response = responses[Math.min(index, responses.length - 1)];
      index += 1;
      return new Response(JSON.stringify(response.body), {
        status: response.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("session and system API client", () => {
  it("reports open mode after a protected endpoint and public session probe succeed", async () => {
    const calls = stubFetchSequence([{ body: {} }, { body: { mode: "open" } }]);
    const result = await sessionApi.probe();
    expect(result).toEqual({ mode: "open", protectedAccess: true });
    expect(calls.map((call) => call.url)).toEqual([`${BASE}/api/cv/status`, `${BASE}/api/session`]);
    expect(calls[0].init?.credentials).toBe("include");
  });

  it("reports secured mode without confirmed access when both checks are rejected", async () => {
    stubFetchSequence([
      { body: { detail: "Unauthorized" }, status: 401 },
      { body: { detail: "Invalid local passphrase" }, status: 401 },
    ]);
    await expect(sessionApi.probe()).resolves.toEqual({ mode: "secured", protectedAccess: false });
  });

  it("reports confirmed protected access for a secured session accepted by a protected endpoint", async () => {
    stubFetchSequence([
      { body: {} },
      { body: { detail: "Invalid local passphrase" }, status: 401 },
    ]);
    await expect(sessionApi.probe()).resolves.toEqual({ mode: "secured", protectedAccess: true });
  });

  it("submits the passphrase directly without storing it in the request client", async () => {
    const calls = stubFetchSequence([{ body: { mode: "secured" } }]);
    await sessionApi.login("local-passphrase");
    expect(calls[0].url).toBe(`${BASE}/api/session`);
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[0].init?.credentials).toBe("include");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ passphrase: "local-passphrase" });
  });

  it("uses the existing public status endpoint for service health", async () => {
    const calls = stubFetchSequence([{ body: { app: "ATM Sentinel", version: "0.1.0", dependencies: {} } }]);
    await systemApi.status();
    expect(calls[0].url).toBe(`${BASE}/api/system/status`);
    expect(calls[0].init?.credentials).toBe("include");
  });
});
