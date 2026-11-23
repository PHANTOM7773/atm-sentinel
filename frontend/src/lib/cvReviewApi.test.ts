import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, cvApi } from "./api";

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

describe("CV review API client", () => {
  it("lists runs with case scope and bounded paging", async () => {
    const calls = stubFetch({ items: [], total: 26, limit: 25, offset: 25 });
    await cvApi.listRuns("case-1", { limit: 25, offset: 25 });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BASE}/api/cv/runs?case_id=case-1&limit=25&offset=25`);
  });

  it("gets one run with case scope", async () => {
    const calls = stubFetch({ cv_run_id: "run-1" });
    await cvApi.getRun("case-1", "run-1");
    expect(calls[0].url).toBe(`${BASE}/api/cv/runs/run-1?case_id=case-1`);
  });

  it("gets observations with case scope and bounded paging", async () => {
    const calls = stubFetch({ items: [], total: 40, limit: 25, offset: 25 });
    await cvApi.getObservations("case-1", "run-1", { limit: 25, offset: 25 });
    expect(calls[0].url).toBe(`${BASE}/api/cv/runs/run-1/observations?case_id=case-1&limit=25&offset=25`);
  });

  it("lists reviews with case scope and a server-accepted bounded limit", async () => {
    const calls = stubFetch({ items: [], total: 0, limit: 200, offset: 0 });
    await cvApi.listReviews("case-1", "run-1", { limit: 200, offset: 0 });
    expect(calls[0].url).toBe(`${BASE}/api/cv/runs/run-1/reviews?case_id=case-1&limit=200&offset=0`);
  });

  it("lists transaction-person associations with case and transaction scope", async () => {
    const calls = stubFetch({ items: [], total: 0, limit: 25, offset: 0, status: "insufficient_evidence", disclaimer: "review only" });
    await cvApi.listPersonAssociations("case-1", "run-1", { transactionId: "tx-1", limit: 25, offset: 0 });
    expect(calls[0].url).toBe(
      `${BASE}/api/cv/runs/run-1/person-associations?case_id=case-1&transaction_id=tx-1&limit=25&offset=0`,
    );
  });

  it("gets best-face evidence with case, run and association scope", async () => {
    const calls = stubFetch({ association_id: "assoc-1", selected: null });
    await cvApi.getBestFace("case-1", "run-1", "assoc-1");
    expect(calls[0].url).toBe(
      `${BASE}/api/cv/runs/run-1/person-associations/assoc-1/best-face?case_id=case-1`,
    );
  });

  it("posts the exact transaction-person association review body", async () => {
    const calls = stubFetch({ association_id: "assoc-1", review_state: "confirmed" });
    await cvApi.reviewPersonAssociation("case-1", "assoc-1", {
      case_id: "case-1",
      cv_run_id: "run-1",
      decision: "rejected",
      reviewer_note: "Insufficient dwell",
    });
    expect(calls[0].url).toBe(`${BASE}/api/cv/person-associations/assoc-1/review?case_id=case-1`);
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      case_id: "case-1",
      cv_run_id: "run-1",
      decision: "rejected",
      reviewer_note: "Insufficient dwell",
    });
  });

  it("gets a single observation review", async () => {
    const calls = stubFetch({ decision_id: "review-1" });
    await cvApi.getReview("case-1", "run-1", "obs-1");
    expect(calls[0].url).toBe(`${BASE}/api/cv/runs/run-1/observations/obs-1/review?case_id=case-1`);
  });

  it("posts the exact upsert review body", async () => {
    const calls = stubFetch({ decision_id: "review-1" }, 201);
    await cvApi.upsertReview("case-1", "run-1", "obs-1", {
      case_id: "case-1",
      cv_run_id: "run-1",
      target_type: "face_observation",
      decision: "relevant",
      reviewer_note: "Reviewed crop",
    });
    expect(calls[0].url).toBe(`${BASE}/api/cv/runs/run-1/observations/obs-1/review?case_id=case-1`);
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[0].init?.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      case_id: "case-1",
      cv_run_id: "run-1",
      target_type: "face_observation",
      decision: "relevant",
      reviewer_note: "Reviewed crop",
    });
  });

  it("builds an opaque crop URL with case and crop references", () => {
    expect(cvApi.cropUrl("case-1", "run-1", "obs-1", "crop-9")).toBe(
      `${BASE}/api/cv/runs/run-1/observations/obs-1/crop?case_id=case-1&crop_id=crop-9`,
    );
  });

  it("posts the exact persistent CV run payload", async () => {
    const calls = stubFetch({ run: { cv_run_id: "run-1" }, observations: { items: [], total: 0, limit: 25, offset: 0 } });
    const payload = {
      case_id: "case-1",
      video_id: "video-1",
      max_frames: 240,
      frame_stride: 2,
      save_crops: true,
      add_to_index: true,
      rank: false,
      summary_only: false,
      window_mode: "full_video" as const,
    };
    await cvApi.createRun(payload);
    expect(calls[0].url).toBe(`${BASE}/api/cv/runs`);
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual(payload);
  });

  it("posts the exact case-scoped candidate search payload", async () => {
    const calls = stubFetch({ items: [], count: 0, limit: 5 });
    const payload = {
      case_id: "case-1",
      query_cv_run_id: "run-1",
      query_observation_id: "obs-1",
      top_k: 5,
      scope: "case_selected_videos" as const,
      source_video_ids: ["video-2"],
    };
    await cvApi.searchCandidates(payload);
    expect(calls[0].url).toBe(`${BASE}/api/cv/candidates/search`);
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual(payload);
  });

  it("throws ApiError with parsed detail and no retry for 404", async () => {
    stubFetch({ detail: "CV run not found" }, 404);
    try {
      await cvApi.getRun("case-1", "missing");
      throw new Error("expected ApiError");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.status).toBe(404);
      expect(apiError.message).toBe("CV run not found");
      expect(apiError.retryAfterSeconds).toBeNull();
    }
  });

  it("throws ApiError with Retry-After for 503", async () => {
    stubFetch({ detail: "CV analysis busy; retry later" }, 503, { "Retry-After": "7" });
    try {
      await cvApi.listRuns("case-1", { limit: 25, offset: 0 });
      throw new Error("expected ApiError");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.status).toBe(503);
      expect(apiError.message).toBe("CV analysis busy; retry later");
      expect(apiError.retryAfterSeconds).toBe(7);
    }
  });
});
