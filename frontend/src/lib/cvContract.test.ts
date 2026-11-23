import { afterEach, describe, expect, it, vi } from "vitest";
import { cvApi } from "./api";
import {
  CV_CANDIDATE_DISCLAIMER,
  CV_CANDIDATE_SCAN_REASONS,
  CV_CANDIDATE_SEARCH_SCOPES,
  CV_ASSOCIATION_EVIDENCE_MEANING,
  CV_ASSOCIATION_EVIDENCE_STRENGTHS,
  CV_ASSOCIATION_LIMITATION,
  CV_ASSOCIATION_REVIEW_STATES,
  CV_ATM_ZONE_COORDINATE_CONVENTION,
  CV_CANDIDATE_VERIFICATION_STATUS,
  CV_CROP_RETRIEVAL_STATES,
  CV_CROP_STATUSES,
  CV_REVIEW_DECISIONS,
  CV_RUN_STATUSES,
  CV_UNSUPPORTED_ATTRIBUTE_STATUS,
  CV_VIDEO_DERIVATIVE_KINDS,
  CV_WINDOW_MODES,
} from "./types";
import type {
  CvCandidateSearchRequest,
  CvCandidateSummary,
  CvHumanReviewDecision,
  CvModelProvenance,
  CvReviewDecision,
  CvReviewFlags,
  CvRunCreateRequest,
  CvRunStatus,
  CvVideoProvenance,
  CvWindowMode,
} from "./types";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CV integration contract", () => {
  it("mirrors lifecycle, review, and window values", () => {
    const status: CvRunStatus = CV_RUN_STATUSES[0];
    const decision: CvReviewDecision = CV_REVIEW_DECISIONS[0];
    const windowMode: CvWindowMode = CV_WINDOW_MODES[0];
    expect(CV_RUN_STATUSES).toEqual([
      "queued",
      "running",
      "completed",
      "completed_with_warnings",
      "failed",
    ]);
    expect(CV_REVIEW_DECISIONS).toEqual(["relevant", "irrelevant", "needs_review"]);
    expect(CV_WINDOW_MODES).toEqual(["full_video", "transaction_aligned"]);
    expect([status, decision, windowMode]).toEqual(["queued", "relevant", "full_video"]);
  });

  it("describes ATM zone and transaction-person association outputs as review-only", () => {
    expect(CV_ATM_ZONE_COORDINATE_CONVENTION).toContain("Frame-relative normalized");
    expect(CV_ASSOCIATION_EVIDENCE_MEANING).toContain("not a calibrated probability");
    expect(CV_ASSOCIATION_LIMITATION).toContain("never identity confirmation");
    expect(CV_ASSOCIATION_REVIEW_STATES).toEqual(["proposed", "confirmed", "rejected", "insufficient_evidence"]);
    expect(CV_ASSOCIATION_EVIDENCE_STRENGTHS).toEqual(["strong", "moderate", "weak", "insufficient"]);
    const request: CvRunCreateRequest = {
      case_id: "case-1",
      video_id: "video-1",
      window_mode: "transaction_aligned",
      transaction_id: "tx-1",
      transaction_ts: "2026-11-22T01:00:00Z",
      cctv_ts: "2026-11-22T01:00:00Z",
      before_seconds: 5,
      after_seconds: 5,
      atm_zone: { name: "atm_keypad", x: 0.5, y: 0.5, width: 0.25, height: 0.25 },
    };
    expect(request.atm_zone?.width).toBe(0.25);
    expect(JSON.stringify(request)).not.toContain("embedding_vector");
  });

  it("marks candidates as human-verification-only with per-model provenance", () => {
    const digest = "a".repeat(64);
    const model: CvModelProvenance = {
      model_key: "sface",
      model_filename: "sface.onnx",
      model_sha256: digest,
      backend: "cpu",
      target: "cpu",
      runtime_state: "configured",
      runtime: {},
      opencv_version: "5.1.0",
      pipeline_version: "cv-phase1-remediated",
      embedding_schema_version: 3,
      generated_at: "2026-11-22T00:00:00Z",
    };
    const candidate: Pick<
      CvCandidateSummary,
      | "verification_status"
      | "requires_human_verification"
      | "candidate_disclaimer"
      | "model_provenance"
      | "candidate_video_provenance"
    > = {
      verification_status: CV_CANDIDATE_VERIFICATION_STATUS,
      requires_human_verification: true,
      candidate_disclaimer: CV_CANDIDATE_DISCLAIMER,
      model_provenance: [model],
      candidate_video_provenance: {
        source_video_id: "video-1",
        source_video_sha256: digest,
        derivative_kind: "none",
      },
    };
    const request: CvRunCreateRequest = {
      case_id: "case-1",
      video_id: "video-1",
      window_mode: "full_video",
    };
    expect(candidate).toEqual({
      verification_status: "candidate_only",
      requires_human_verification: true,
      candidate_disclaimer:
        "Similarity candidate only; requires human verification. Never identity confirmation.",
      model_provenance: [model],
      candidate_video_provenance: {
        source_video_id: "video-1",
        source_video_sha256: digest,
        derivative_kind: "none",
      },
    });
    expect(request.window_mode).toBe("full_video");
    expect(JSON.stringify(candidate)).not.toContain("embedding_vector");
  });

  it("uses opaque crops, separate video provenance, and honest attribute statuses", () => {
    const digest = "b".repeat(64);
    const derivativeDigest = "c".repeat(64);
    const videoProvenance: CvVideoProvenance = {
      source_video_id: "video-1",
      source_video_sha256: digest,
      derivative_kind: "normalized",
      normalized_video_id: "video-norm-1",
      normalized_video_sha256: derivativeDigest,
    };
    const flags: CvReviewFlags = {
      low_sharpness: false,
      underexposed: false,
      overexposed: false,
      small_face: false,
      pose_away: false,
      partial_occlusion_suspected: false,
      mask: CV_UNSUPPORTED_ATTRIBUTE_STATUS,
      helmet: CV_UNSUPPORTED_ATTRIBUTE_STATUS,
      cap: CV_UNSUPPORTED_ATTRIBUTE_STATUS,
    };
    expect(CV_CROP_STATUSES).toEqual(["not_generated", "available", "unavailable", "retired"]);
    expect(CV_CROP_RETRIEVAL_STATES).toEqual([
      "not_requested",
      "retrievable",
      "pending",
      "expired",
      "not_supported",
    ]);
    expect(CV_UNSUPPORTED_ATTRIBUTE_STATUS).toBe("not_assessed");
    expect(CV_VIDEO_DERIVATIVE_KINDS).toEqual(["none", "normalized"]);
    expect(videoProvenance.source_video_sha256).toBe(digest);
    expect(videoProvenance.normalized_video_sha256).toBe(derivativeDigest);
    expect(JSON.stringify(flags)).not.toContain("confirmed");
    expect(JSON.stringify({ crop_id: "crop-opaque-1", status: "available", retrieval_state: "not_supported" })).not.toContain("/");
  });

  it("keeps candidate scope case-only and reviewer notes optional", () => {
    expect(CV_CANDIDATE_SEARCH_SCOPES).toEqual(["case_all_eligible_videos", "case_selected_videos"]);
    expect(CV_CANDIDATE_SCAN_REASONS).toEqual(["scan_limit", "top_k_reached", "exhausted"]);
    const search: CvCandidateSearchRequest = {
      case_id: "case-1",
      query_cv_run_id: "run-1",
      query_observation_id: "obs-1",
      scope: CV_CANDIDATE_SEARCH_SCOPES[0],
    };
    const review: CvHumanReviewDecision = {
      decision_id: "review-1",
      case_id: "case-1",
      cv_run_id: "run-1",
      target_type: "candidate",
      target_id: "candidate-1",
      decision: "needs_review",
      created_at: "2026-11-22T00:00:00Z",
    };
    expect(Object.keys(search)).not.toContain("exclude_query_source");
    expect(search.scope).toBe("case_all_eligible_videos");
    expect(review.reviewer_note).toBeUndefined();
  });

  it("exposes typed client methods for read-only CV endpoints", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        calls.push(String(input));
        return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );

    await cvApi.status();
    await cvApi.analyze({ video_id: "video-1" });
    await cvApi.embeddings();

    expect(calls).toEqual([
      "http://127.0.0.1:8000/api/cv/status",
      "http://127.0.0.1:8000/api/cv/analyze",
      "http://127.0.0.1:8000/api/cv/embeddings",
    ]);
  });
});
