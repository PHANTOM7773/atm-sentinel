import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import {
  CvAssociationCard,
  CvCandidateSearchPanel,
  CvObservationCard,
  CvReviewForm,
  CvRunCreateForm,
  CvRunDetailView,
  CvRunHistoryView,
  buildCvRunPayload,
  candidateSearchErrorMessage,
  cvRunFieldsValid,
  initialCvRunFormValues,
  reviewErrorMessage,
} from "./CvRuns";
import { AppShell } from "../components/AppShell";
import { ApiError, cvApi } from "../lib/api";
import { CV_ASSOCIATION_EVIDENCE_MEANING, CV_ASSOCIATION_LIMITATION, CV_CANDIDATE_DISCLAIMER, CV_REVIEW_DECISIONS } from "../lib/types";
import type {
  CaseRecord,
  CvCandidateSearchResponse,
  CvCandidateSummary,
  CvFaceObservationSummary,
  CvHumanReviewDecision,
  CvRunSummary,
  TransactionRecord,
  TransactionPersonAssociationRecord,
  VideoRecord,
} from "../lib/types";

function render(node: Parameters<typeof renderToStaticMarkup>[0]): string {
  return renderToStaticMarkup(createElement(MemoryRouter, { initialEntries: ["/cv?case=case-1"] }, node));
}

const cases: CaseRecord[] = [{
  id: "case-1",
  case_number: "DEMO-1",
  title: "Demo case",
  location: "ATM-01",
  tags: "demo",
  status: "active",
  created_at: "2026-11-22T00:00:00Z",
  updated_at: "2026-11-22T00:00:00Z",
}];

function makeRun(overrides: Partial<CvRunSummary> = {}): CvRunSummary {
  return {
    cv_run_id: "run-1",
    case_id: "case-1",
    video_provenance: { source_video_id: "video-1", source_video_sha256: "a".repeat(64), derivative_kind: "none" },
    status: "completed",
    window_mode: "transaction_aligned",
    analysis_run_id: "analysis-1",
    created_at: "2026-11-22T00:00:00Z",
    message: "completed",
    warnings: [],
    budget: {
      requested_max_frames: 100,
      analyzed_frames: 50,
      frame_stride: 1,
      max_analysis_frames: 500,
      max_frame_stride: 5,
      max_decoded_frames: 1000,
      max_clip_duration_seconds: 600,
      max_top_k: 20,
      max_response_bytes: 1_000_000,
      concurrent_analyses: 1,
      synchronous: true,
    },
    truncation: {
      truncated: false,
      face_observations_omitted: 0,
      person_observations_omitted: 0,
      ranking_candidates_omitted: 0,
      frames_omitted: 0,
      reasons: [],
    },
    disclaimer: "candidate only",
    observation_count: 2,
    window: {
      mode: "transaction_aligned",
      start_seconds: 10,
      end_seconds: 20,
      duration_seconds: 10,
      source_video_duration_seconds: 60,
      is_full_video: false,
      before_seconds: 5,
      after_seconds: 5,
      clamped: false,
      warnings: [],
    },
    ...overrides,
  };
}

function makeObservation(overrides: Partial<CvFaceObservationSummary> = {}): CvFaceObservationSummary {
  return {
    observation_id: "obs-1",
    cv_sample_id: "sample-1",
    cv_run_id: "run-1",
    case_id: "case-1",
    video_provenance: { source_video_id: "video-1", source_video_sha256: "b".repeat(64), derivative_kind: "none" },
    original_frame_number: 42,
    original_video_timestamp_seconds: 12.5,
    bbox: [1, 2, 3, 4],
    detector_confidence: 0.8,
    quality: {
      quality_score: 82,
      sharpness: 70,
      brightness: 120,
      contrast: 40,
      face_size_px: 60,
      components: {},
      warnings: [],
      disclaimer: "quality is a proxy",
    },
    review_flags: {
      low_sharpness: false,
      underexposed: false,
      overexposed: false,
      small_face: false,
      pose_away: false,
      partial_occlusion_suspected: true,
      mask: "not_assessed",
      helmet: "not_assessed",
      cap: "not_assessed",
    },
    pose: {
      roll_proxy_deg: 1.2,
      yaw_proxy: 0.4,
      pitch_proxy: -0.3,
      frontal_score: 0.9,
      warnings: [],
      method: "geometric proxies",
    },
    crop: { available: false, status: "not_generated", retrieval_state: "not_supported" },
    verification_status: "candidate_only",
    requires_human_verification: true,
    candidate_disclaimer: "candidate only",
    ...overrides,
  };
}

function makeReview(overrides: Partial<CvHumanReviewDecision> = {}): CvHumanReviewDecision {
  return {
    decision_id: "review-1",
    case_id: "case-1",
    cv_run_id: "run-1",
    target_type: "face_observation",
    target_id: "obs-1",
    decision: "relevant",
    reviewer_note: "Checked against case notes",
    created_at: "2026-11-22T00:00:00Z",
    ...overrides,
  };
}

function makeVideo(overrides: Partial<VideoRecord> = {}): VideoRecord {
  return {
    id: "video-2",
    case_id: "case-1",
    original_filename: "second.mp4",
    stored_path: "second.mp4",
    size_bytes: 1000,
    sha256: "d".repeat(64),
    tags: "",
    container: "mp4",
    codec: "h264",
    width: 640,
    height: 360,
    fps: 25,
    duration: 60,
    stream_count: 2,
    integrity_status: "verified",
    integrity_detail: "",
    uploaded_at: "2026-11-22T00:00:00Z",
    ...overrides,
  };
}

function makeTransaction(overrides: Partial<TransactionRecord> = {}): TransactionRecord {
  return {
    id: "tx-1",
    case_id: "case-1",
    reference: "TX-1",
    atm_id: "ATM-1",
    transaction_ts: "2026-11-22T01:00:00Z",
    cctv_ts: "2026-11-22T01:00:00Z",
    transaction_type: "withdrawal",
    amount: "100",
    note: "",
    created_at: "2026-11-22T00:00:00Z",
    ...overrides,
  };
}

function makeCandidate(overrides: Partial<CvCandidateSummary> = {}): CvCandidateSummary {
  return {
    candidate_id: "candidate-1",
    case_id: "case-1",
    query_cv_run_id: "run-1",
    query_observation_id: "obs-1",
    candidate_cv_run_id: "run-2",
    candidate_observation_id: "obs-2",
    candidate_video_provenance: { source_video_id: "video-2", source_video_sha256: "d".repeat(64), derivative_kind: "none" },
    candidate_original_frame_number: 101,
    candidate_original_video_timestamp_seconds: 30,
    candidate_analysis_relative_timestamp_seconds: 30,
    candidate_extracted_frame_id: null,
    similarity_score: 0.9468,
    rank: 1,
    model_provenance: [{
      model_key: "sface",
      model_filename: "sface.onnx",
      model_sha256: "e".repeat(64),
      model_source_url: null,
      backend: "cpu",
      target: "cpu",
      runtime_state: "configured",
      runtime: {},
      opencv_version: "5.1.0",
      pipeline_version: "cv-phase2",
      embedding_schema_version: 4,
      generated_at: "2026-11-22T00:00:00Z",
    }],
    human_review_status: null,
    candidate_quality: makeObservation().quality,
    candidate_review_flags: makeObservation().review_flags,
    candidate_crop: { available: true, status: "available", retrieval_state: "retrievable", crop_id: "crop-c" },
    verification_status: "candidate_only",
    requires_human_verification: true,
    candidate_disclaimer: CV_CANDIDATE_DISCLAIMER,
    score_meaning: "Cosine similarity of local embeddings; not an identity decision.",
    ...overrides,
  };
}

function makeCandidateResult(overrides: Partial<CvCandidateSearchResponse> = {}): CvCandidateSearchResponse {
  return {
    items: [makeCandidate()],
    count: 1,
    limit: 5,
    scope: "case_all_eligible_videos",
    source_video_ids: [],
    query: { case_id: "case-1", cv_run_id: "run-1", observation_id: "obs-1" },
    score_meaning: "Cosine similarity of local embeddings; not an identity decision.",
    disclaimer: CV_CANDIDATE_DISCLAIMER,
    index: { generation: 4, schema_version: 4, record_count: 53, provenance: { known: 53, legacy_unknown: 0 } },
    limits: {
      max_top_k: 25,
      concurrent_analyses: 1,
      candidate_scan: { limit: 120, scanned: 12, truncated: false, reason: "exhausted" },
    },
    ...overrides,
  };
}

function makeAssociation(overrides: Partial<TransactionPersonAssociationRecord> = {}): TransactionPersonAssociationRecord {
  return {
    association_id: "assoc-1",
    case_id: "case-1",
    transaction_id: "tx-1",
    cv_run_id: "run-1",
    video_provenance: { source_video_id: "video-1", source_video_sha256: "a".repeat(64), derivative_kind: "none" },
    zone_id: "zone-1",
    person_track_id: 7,
    review_state: "proposed",
    evidence_strength: "strong",
    heuristic_score: 0.8123,
    score_meaning: CV_ASSOCIATION_EVIDENCE_MEANING,
    dwell_seconds: 1.4,
    zone_frame_count: 14,
    transaction_window_overlap_seconds: 1.2,
    first_video_timestamp_seconds: 2.1,
    last_video_timestamp_seconds: 3.5,
    transaction_video_seconds: 3,
    window_start_seconds: 2,
    window_end_seconds: 4,
    evidence: {},
    reviewer_note: null,
    reviewed_at: null,
    created_at: "2026-11-22T00:00:00Z",
    updated_at: "2026-11-22T00:00:00Z",
    verification_status: "candidate_only",
    requires_human_verification: true,
    association_disclaimer: CV_ASSOCIATION_LIMITATION,
    ...overrides,
  };
}

describe("CV run presentational views", () => {
  it("renders history runs with case context, status, window, video and observation count", () => {
    const html = render(createElement(CvRunHistoryView, {
      cases,
      caseId: "case-1",
      onCaseChange: () => {},
      runs: [makeRun()],
      total: 1,
      offset: 0,
    }));
    expect(html).toContain("run-1");
    expect(html).toContain("completed");
    expect(html).toContain("transaction_aligned");
    expect(html).toContain("video-1");
    expect(html).toContain("Observations: 2");
    expect(html).toContain("/cv?case=case-1&amp;run=run-1");
  });

  it("renders the history empty state", () => {
    const html = render(createElement(CvRunHistoryView, {
      cases,
      caseId: "case-1",
      onCaseChange: () => {},
      runs: [],
      total: 0,
      offset: 0,
    }));
    expect(html).toContain("No CV runs yet");
  });

  it("renders history loading and error states", () => {
    const loading = render(createElement(CvRunHistoryView, {
      cases,
      caseId: "case-1",
      onCaseChange: () => {},
      runs: [],
      total: 0,
      offset: 0,
      loading: true,
    }));
    expect(loading).toContain("Loading CV runs");

    const failedRequest = render(createElement(CvRunHistoryView, {
      cases,
      caseId: "case-1",
      onCaseChange: () => {},
      runs: [],
      total: 0,
      offset: 0,
      error: "Cannot reach the local API",
    }));
    expect(failedRequest).toContain("Cannot reach the local API");
  });

  it("renders a failed run state", () => {
    const html = render(createElement(CvRunHistoryView, {
      cases,
      caseId: "case-1",
      onCaseChange: () => {},
      runs: [makeRun({ status: "failed", message: "analysis crashed" })],
      total: 1,
      offset: 0,
    }));
    expect(html).toContain("failed");
    expect(html).toContain("Run failed");
    expect(html).toContain("analysis crashed");
  });

  it("renders run metadata, window, warnings and truncation in detail", () => {
    const html = render(createElement(CvRunDetailView, {
      caseId: "case-1",
      runId: "run-1",
      run: makeRun({
        warnings: ["clock drift"],
        truncation: {
          truncated: true,
          face_observations_omitted: 3,
          person_observations_omitted: 1,
          ranking_candidates_omitted: 2,
          frames_omitted: 4,
          reasons: ["response limit"],
        },
      }),
      observations: [],
      reviews: [],
      totalObservations: 0,
      offset: 0,
    }));
    expect(html).toContain("Transaction-aligned window");
    expect(html).toContain("Warnings: clock drift");
    expect(html).toContain("Analysis output truncated");
    expect(html).toContain("3 face observations");
  });

  it("renders transaction-person associations in run detail", () => {
    const html = render(createElement(CvRunDetailView, {
      caseId: "case-1",
      runId: "run-1",
      run: makeRun(),
      observations: [],
      reviews: [],
      associations: {
        items: [makeAssociation()],
        total: 1,
        limit: 25,
        offset: 0,
        status: "proposed",
        disclaimer: CV_ASSOCIATION_LIMITATION,
      },
      totalObservations: 0,
      offset: 0,
    }));
    expect(html).toContain("Transaction-person associations");
    expect(html).toContain("assoc-1");
    expect(html).toContain("Save association review");
    expect(html).toContain(CV_ASSOCIATION_LIMITATION);
  });

  it("renders an unknown transaction video time as unavailable rather than zero", () => {
    const html = render(createElement(CvRunDetailView, {
      caseId: "case-1",
      runId: "run-1",
      run: makeRun({
        timestamp_provenance: {
          cv_run_id: "run-1",
          analysis_run_id: "analysis-1",
          video_provenance: { source_video_id: "video-1", source_video_sha256: "a".repeat(64), derivative_kind: "none" },
          transaction_video_seconds: null,
          window_start_seconds: 10,
          window_end_seconds: 20,
          timebase: "source_video_seconds",
          warnings: [],
        },
      }),
      observations: [],
      reviews: [],
      totalObservations: 0,
      offset: 0,
    }));
    expect(html).toContain("Timestamp provenance");
    expect(html).toMatch(/Transaction video time[\s\S]{0,180}—/);
    expect(html).not.toMatch(/Transaction video time[\s\S]{0,180}00:00\.00/);
  });

  it("exposes best-face ranking detail and association pagination controls", () => {
    const association = makeAssociation({
      best_face: {
        status: "selected",
        selected_observation_id: "face-obs-1",
        selected_frame_number: 42,
        selected_timestamp_seconds: 12.5,
        selected_selection_score: 0.8123,
        selected_reliability_status: "limited",
        selected_reliability_summary: "Usable with limitations.",
        ranked_frame_count: 3,
        rejected_frame_count: 2,
        other_person_frame_count: 1,
        score_meaning: "Quality-ranking heuristic score; not identity confidence.",
        limitation: "Frame-to-person linkage is bbox evidence, not identity.",
      },
    });
    const card = render(createElement(CvAssociationCard, {
      caseId: "case-1",
      runId: "run-1",
      association,
    }));
    expect(card).toContain("Inspect ranking");

    const detail = render(createElement(CvRunDetailView, {
      caseId: "case-1",
      runId: "run-1",
      run: makeRun(),
      observations: [],
      reviews: [],
      associations: {
        items: [association],
        total: 40,
        limit: 25,
        offset: 0,
        status: "proposed",
        disclaimer: CV_ASSOCIATION_LIMITATION,
      },
      totalObservations: 0,
      offset: 0,
    }));
    expect(detail).toContain("Showing 1–1 of 40 associations");
    expect(detail).toContain("Next");
  });

  it("renders observation pagination controls for one bounded page", () => {
    const observations = Array.from({ length: 25 }, (_, index) => makeObservation({ observation_id: `obs-${index}` }));
    const html = render(createElement(CvRunDetailView, {
      caseId: "case-1",
      runId: "run-1",
      run: null,
      observations,
      reviews: [],
      totalObservations: 50,
      offset: 0,
      limit: 25,
    }));
    expect(html).toContain("Previous");
    expect(html).toContain("Next");
    expect(html).toContain("Showing 1–25 of 50 observations");
  });

  it("renders a graceful crop unavailable state without an image", () => {
    const html = render(createElement(CvObservationCard, {
      caseId: "case-1",
      runId: "run-1",
      observation: makeObservation(),
    }));
    expect(html).toContain("Crop unavailable");
    expect(html).not.toContain("<img");
    expect(html).toContain("candidate_only");
    expect(html).toContain("not assessed");
    expect(html).toContain("Possible partial occlusion");
    expect(html).toContain("Select for export");
    expect(html).toContain(CV_ASSOCIATION_LIMITATION);
    expect(html.toLowerCase()).not.toContain("suspect");
    expect(html.toLowerCase()).not.toContain("identified");
  });

  it("renders an image only for metadata marked retrievable", () => {
    const observation = makeObservation({
      observation_id: "obs-crop",
      crop: { available: true, status: "available", retrieval_state: "retrievable", crop_id: "crop-9" },
    });
    const html = render(createElement(CvObservationCard, {
      caseId: "case-1",
      runId: "run-1",
      observation,
    }));
    expect(html).toContain("<img");
    expect(html).toContain(`crop?case_id=case-1&amp;crop_id=crop-9`);
    expect(html).toContain(
      cvApi.cropUrl("case-1", "run-1", "obs-crop", "crop-9").replaceAll("&", "&amp;"),
    );
  });

  it("does not render an image when crop metadata is expired", () => {
    const html = render(createElement(CvObservationCard, {
      caseId: "case-1",
      runId: "run-1",
      observation: makeObservation({
        crop: { available: true, status: "available", retrieval_state: "expired", crop_id: "crop-9" },
      }),
    }));
    expect(html).toContain("Crop unavailable");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("crop_id=crop-9");
  });

  it("offers every review decision and an optional reviewer note", () => {
    const html = render(createElement(CvReviewForm, {}));
    for (const decision of CV_REVIEW_DECISIONS) expect(html).toContain(`value="${decision}"`);
    expect(html).toContain("Reviewer note");
    expect(html).toContain("Save review");
  });

  it("shows a saved decision, note and update affordance", () => {
    const form = render(createElement(CvReviewForm, {
      decision: "irrelevant",
      reviewerNote: "Checked crop",
      savedAt: "2026-11-22T01:00:00Z",
    }));
    expect(form).toContain("Saved review");
    expect(form).toContain("irrelevant");
    expect(form).toContain("Checked crop");
    expect(form).toContain("Update review");

    const detail = render(createElement(CvRunDetailView, {
      caseId: "case-1",
      runId: "run-1",
      run: makeRun(),
      observations: [makeObservation()],
      reviews: [makeReview({ decision: "irrelevant", reviewer_note: "Checked crop" })],
      totalObservations: 1,
      offset: 0,
    }));
    expect(detail).toContain("Saved review");
    expect(detail).toContain("Checked crop");
    expect(detail).toContain("Update review");
  });

  it("disables the save control while a review is in progress", () => {
    const html = render(createElement(CvReviewForm, { decision: "relevant", saving: true }));
    expect(html).toContain("disabled=");
    expect(html).toContain("Update review");
  });

  it("maps 404, 409, 422 and 503 review errors to actionable messages", () => {
    expect(reviewErrorMessage(new ApiError("missing", 404))).toContain("no longer exists");
    expect(reviewErrorMessage(new ApiError("conflict", 409))).toContain("changed elsewhere");
    expect(reviewErrorMessage(new ApiError("invalid", 422))).toContain("could not be saved");
    expect(reviewErrorMessage(new ApiError("busy", 503, 7))).toContain("Retry in 7 seconds");
    expect(reviewErrorMessage(new ApiError("busy", 503))).toContain("Retry shortly");
  });

  it("builds bounded full-video and transaction-aligned run payloads", () => {
    expect(buildCvRunPayload("case-1", { ...initialCvRunFormValues, videoId: "video-1" }, [])).toEqual({
      case_id: "case-1",
      video_id: "video-1",
      max_frames: 240,
      frame_stride: 1,
      save_crops: true,
      add_to_index: true,
      rank: false,
      summary_only: false,
      window_mode: "full_video",
    });

    const aligned = buildCvRunPayload(
      "case-1",
      {
        ...initialCvRunFormValues,
        videoId: "video-1",
        windowMode: "transaction_aligned",
        transactionId: "tx-1",
        beforeSeconds: "15",
        afterSeconds: "25",
      },
      [makeTransaction()],
    );
    expect(aligned).toMatchObject({
      case_id: "case-1",
      video_id: "video-1",
      window_mode: "transaction_aligned",
      transaction_id: "tx-1",
      transaction_ts: "2026-11-22T01:00:00Z",
      cctv_ts: "2026-11-22T01:00:00Z",
      before_seconds: 15,
      after_seconds: 25,
      video_start_ts: null,
      cctv_reference_video_time: 0,
    });
  });

  it("keeps CV run budgets within local analysis limits", () => {
    expect(cvRunFieldsValid(initialCvRunFormValues)).toBe(true);
    expect(cvRunFieldsValid({ ...initialCvRunFormValues, maxFrames: "301" })).toBe(false);
    expect(cvRunFieldsValid({ ...initialCvRunFormValues, maxFrames: "" })).toBe(false);
    expect(cvRunFieldsValid({ ...initialCvRunFormValues, frameStride: "21" })).toBe(false);
    expect(cvRunFieldsValid({
      ...initialCvRunFormValues,
      windowMode: "transaction_aligned",
      cctvReferenceVideoTime: "-1",
    })).toBe(false);
    expect(cvRunFieldsValid({
      ...initialCvRunFormValues,
      windowMode: "transaction_aligned",
      cctvReferenceVideoTime: "7.5",
    })).toBe(true);
  });

  it("sends the configured CCTV reference point in aligned run payloads", () => {
    const payload = buildCvRunPayload(
      "case-1",
      {
        ...initialCvRunFormValues,
        videoId: "video-1",
        windowMode: "transaction_aligned",
        transactionId: "tx-1",
        cctvReferenceVideoTime: "7.5",
      },
      [makeTransaction()],
    );
    expect(payload.cctv_reference_video_time).toBe(7.5);
  });

  it("builds a normalized ATM zone payload for transaction-aligned runs", () => {
    const payload = buildCvRunPayload(
      "case-1",
      {
        ...initialCvRunFormValues,
        videoId: "video-1",
        windowMode: "transaction_aligned",
        transactionId: "tx-1",
        atmZoneEnabled: true,
        atmZoneName: "atm_keypad",
        atmZoneX: "0.4",
        atmZoneY: "0.35",
        atmZoneWidth: "0.2",
        atmZoneHeight: "0.25",
      },
      [makeTransaction()],
    );
    expect(payload.atm_zone).toEqual({ name: "atm_keypad", x: 0.4, y: 0.35, width: 0.2, height: 0.25 });

    const html = render(createElement(CvRunCreateForm, {
      cases,
      caseId: "case-1",
      videos: [],
      transactions: [makeTransaction()],
      form: {
        ...initialCvRunFormValues,
        windowMode: "transaction_aligned",
        atmZoneEnabled: true,
      },
      onCaseChange: () => {},
      onFormChange: () => {},
      onCreate: () => {},
    }));
    expect(html).toContain("Associate detected people with an ATM interaction zone");
    expect(html).toContain("Zone name");
    expect(html).toContain("Frame-relative normalized");
    expect(html.toLowerCase()).not.toContain("identified");
  });

  it("renders transaction-person association evidence and review controls without identity claims", () => {
    const html = render(createElement(CvAssociationCard, {
      caseId: "case-1",
      runId: "run-1",
      association: makeAssociation(),
      onReview: () => {},
    }));
    expect(html).toContain("assoc-1");
    expect(html).toContain("Track 7");
    expect(html).toContain("0.8123");
    expect(html).toContain("Zone frames");
    expect(html).toContain("Save association review");
    expect(html).toContain("confirmed");
    expect(html).toContain("rejected");
    expect(html).toContain(CV_ASSOCIATION_LIMITATION);
    expect(html).toContain(CV_ASSOCIATION_EVIDENCE_MEANING);
    expect(html.toLowerCase()).not.toContain("identified");
  });

  it("renders the backend best-face summary without making an identity claim", () => {
    const selectedHtml = render(createElement(CvAssociationCard, {
      caseId: "case-1",
      runId: "run-1",
      association: makeAssociation({
        best_face: {
          status: "selected",
          selected_observation_id: "face-obs-1",
          selected_frame_number: 42,
          selected_timestamp_seconds: 12.5,
          selected_selection_score: 0.8123,
          selected_reliability_status: "limited",
          selected_reliability_summary: "Image quality is usable but has limitations.",
          ranked_frame_count: 3,
          rejected_frame_count: 2,
          other_person_frame_count: 1,
          score_meaning: "Quality-ranking heuristic score; not identity confidence.",
          limitation: "Frame-to-person linkage is bbox evidence, not identity.",
        },
      }),
      onReview: () => {},
    }));
    expect(selectedHtml).toContain("Best face frame (quality ranking only)");
    expect(selectedHtml).toContain("face-obs-1");
    expect(selectedHtml).toContain("0.8123");
    expect(selectedHtml).toContain("reliability: limited");
    expect(selectedHtml).toContain("Image quality is usable but has limitations.");
    expect(selectedHtml).toContain("mask/helmet/cap are not assessed");
    expect(selectedHtml).toContain("Ranked 3");
    expect(selectedHtml).toContain("Quality-ranking heuristic score; not identity confidence.");
    expect(selectedHtml.toLowerCase()).not.toContain("identified");

    const noSelectionHtml = render(createElement(CvAssociationCard, {
      caseId: "case-1",
      runId: "run-1",
      association: makeAssociation({
        best_face: {
          status: "no_selection",
          ranked_frame_count: 0,
          rejected_frame_count: 2,
          other_person_frame_count: 0,
          no_selection_reason: "no_eligible_face_for_person",
          score_meaning: "Quality-ranking heuristic score; not identity confidence.",
          limitation: "Frame-to-person linkage is bbox evidence, not identity.",
        },
      }),
    }));
    expect(noSelectionHtml).toContain("no_eligible_face_for_person");
    expect(noSelectionHtml).toContain("No usable face frame was selected");
  });

  it("shows the insufficient-evidence association state without review controls", () => {
    const html = render(createElement(CvAssociationCard, {
      caseId: "case-1",
      runId: "run-1",
      association: makeAssociation({ review_state: "insufficient_evidence", evidence_strength: "insufficient", person_track_id: null }),
    }));
    expect(html).toContain("insufficient_evidence");
    expect(html).toContain("No person track crossed the zone");
    expect(html).not.toContain("Save association review");
  });

  it("renders the run creation form without selecting a case automatically", () => {
    const html = render(createElement(CvRunCreateForm, {
      cases,
      caseId: "",
      videos: [],
      transactions: [],
      form: initialCvRunFormValues,
      onCaseChange: () => {},
      onFormChange: () => {},
      onCreate: () => {},
    }));
    expect(html).toContain("Start CV candidate analysis");
    expect(html).toContain("Source video");
    expect(html).toContain("Start candidate analysis");
    expect(html).toContain("disabled=");
    expect(html).toContain("Face detection locates face regions");
    expect(html).toContain("Ranking is not identity confidence or probability");
    expect(html.toLowerCase()).toContain("no identity inference");
  });

  it("offers query selection with a disabled state for non-eligible runs", () => {
    const enabled = render(createElement(CvObservationCard, {
      caseId: "case-1",
      runId: "run-1",
      observation: makeObservation(),
      querySelectable: true,
      onSelectQuery: () => {},
    }));
    expect(enabled).toContain("Use as similarity query");

    const disabled = render(createElement(CvObservationCard, {
      caseId: "case-1",
      runId: "run-1",
      observation: makeObservation(),
      querySelectable: false,
      onSelectQuery: () => {},
    }));
    expect(disabled).toContain("Use as similarity query");
    expect(disabled).toContain("disabled=");
  });

  it("renders candidate scan diagnostics, provenance, flags and review controls", () => {
    const html = render(createElement(CvCandidateSearchPanel, {
      caseId: "case-1",
      runId: "run-1",
      videos: [makeVideo()],
      queryObservation: makeObservation(),
      querySourceVideoId: "video-1",
      scope: "case_all_eligible_videos",
      sourceVideoIds: [],
      topK: "5",
      result: makeCandidateResult(),
      onScopeChange: () => {},
      onSourceVideoToggle: () => {},
      onTopKChange: () => {},
      onSearch: () => {},
      onReview: () => {},
    }));
    expect(html).toContain("Scan diagnostics");
    expect(html).toContain("Scan limit");
    expect(html).toContain("exhausted");
    expect(html).toContain("sface");
    expect(html).toContain("Crop state:");
    expect(html).toContain("retrievable");
    expect(html).toContain("Possible partial occlusion");
    expect(html).toContain("Save review");
    expect(html).toContain("Select for export");
    expect(html).toContain(CV_ASSOCIATION_LIMITATION);
    expect(html.toLowerCase()).toContain("candidate only");
    expect(html.toLowerCase()).not.toContain("identified");
    expect(html).not.toContain("embedding_vector");
  });

  it("excludes the query source video from selected-video scope", () => {
    const html = render(createElement(CvCandidateSearchPanel, {
      caseId: "case-1",
      runId: "run-1",
      videos: [
        makeVideo({ id: "video-1", original_filename: "query.mp4" }),
        makeVideo({ id: "video-2", original_filename: "other.mp4" }),
      ],
      queryObservation: makeObservation(),
      querySourceVideoId: "video-1",
      scope: "case_selected_videos",
      sourceVideoIds: [],
      topK: "5",
      result: null,
      onScopeChange: () => {},
      onSourceVideoToggle: () => {},
      onTopKChange: () => {},
      onSearch: () => {},
    }));
    expect(html).toContain("other.mp4");
    expect(html).not.toContain("query.mp4");
    expect(html).not.toContain("video-1");
    expect(html).toContain("excluded automatically");
  });

  it("maps missing embeddings and busy candidate searches to actionable messages", () => {
    expect(candidateSearchErrorMessage(new ApiError("Query embedding unavailable", 404))).toContain("no usable embedding");
    expect(candidateSearchErrorMessage(new ApiError("busy", 503, 7))).toContain("Retry in 7 seconds");
  });

  it("preserves the selected case in primary navigation links", () => {
    const html = render(createElement(AppShell, null, createElement("div")));
    expect(html).toContain('href="/investigation?case=case-1"');
    expect(html).toContain('href="/evidence?case=case-1"');
    expect(html).toContain('href="/cv?case=case-1"');
    expect(html).toContain('href="/export?case=case-1"');
  });
});
