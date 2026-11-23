import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, cvApi } from "./api";

const BASE = "http://127.0.0.1:8000";

interface FetchCall {
  url: string;
  init?: RequestInit;
}

function stubFetch(body: unknown, status = 200, headers: Record<string, string> = {}): FetchCall[] {
  const calls: FetchCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json", ...headers },
      });
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TASK 19 workflow API client", () => {
  it("posts enhancement requests with case/run/observation/crop scope", async () => {
    const calls = stubFetch({ preset: "general_enhancement", enhanced_sha256: "b".repeat(64) });
    await cvApi.enhanceCrop({
      case_id: "case-1",
      cv_run_id: "run-1",
      observation_id: "obs-1",
      crop_id: "crop-1",
      preset: "general_enhancement",
    });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BASE}/api/cv/enhancement/face-crop`);
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      case_id: "case-1",
      cv_run_id: "run-1",
      observation_id: "obs-1",
      crop_id: "crop-1",
      preset: "general_enhancement",
    });
    expect(cvApi.enhancedCropUrl("case-1", "run-1", "obs-1", "crop-1", "general_enhancement")).toBe(
      `${BASE}/api/cv/enhancement/face-crop/image?case_id=case-1&cv_run_id=run-1&observation_id=obs-1&crop_id=crop-1&preset=general_enhancement`,
    );
  });

  it("posts candidate search and CV export payloads without extra fields", async () => {
    const calls = stubFetch({ count: 0, items: [] });
    await cvApi.searchCandidates({
      case_id: "case-1",
      query_cv_run_id: "run-1",
      query_observation_id: "obs-1",
      top_k: 5,
      scope: "case_all_eligible_videos",
      disclaimer: "candidate only",
    });
    await api.post("/api/exports", {
      case_id: "case-1",
      frame_ids: ["frame-1"],
      cv_items: [{ kind: "observation", cv_run_id: "run-1", observation_id: "obs-1" }],
    });
    expect(calls).toHaveLength(2);
    expect(calls[0].url).toBe(`${BASE}/api/cv/candidates/search`);
    expect(calls[1].url).toBe(`${BASE}/api/exports`);
    expect(JSON.parse(String(calls[1].init?.body))).toEqual({
      case_id: "case-1",
      frame_ids: ["frame-1"],
      cv_items: [{ kind: "observation", cv_run_id: "run-1", observation_id: "obs-1" }],
    });
  });

  it("surfaces controlled API errors without exposing raw failure detail types", async () => {
    stubFetch({ detail: "CV analysis busy; retry later" }, 503, { "Retry-After": "5" });
    try {
      await cvApi.createRun({
        case_id: "case-1",
        video_id: "video-1",
        window_mode: "full_video",
      });
      throw new Error("expected ApiError");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.message).toBe("CV analysis busy; retry later");
      expect(apiError.status).toBe(503);
      expect(apiError.retryAfterSeconds).toBe(5);
    }
  });
});
