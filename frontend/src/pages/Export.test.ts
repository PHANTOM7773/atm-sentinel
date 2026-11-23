import { describe, expect, it } from "vitest";
import {
  buildExportPayload,
  candidateToCvExportItem,
  normalizeCvExportItem,
  observationToCvExportItem,
  parseDraftCvItems,
} from "./Export";
import { CV_CANDIDATE_DISCLAIMER } from "../lib/types";
import type { CvCandidateSummary, CvExportItem, CvFaceObservationSummary } from "../lib/types";

const observation = {
  cv_run_id: "run-1",
  observation_id: "obs-1",
} as unknown as CvFaceObservationSummary;

const candidate = {
  candidate_id: "candidate-1",
  query_cv_run_id: "run-1",
  query_observation_id: "obs-1",
  candidate_cv_run_id: "run-2",
  candidate_observation_id: "obs-2",
  similarity_score: 0.91,
  rank: 2,
  candidate_disclaimer: CV_CANDIDATE_DISCLAIMER,
  score_meaning: "Cosine similarity; not identity.",
} as unknown as CvCandidateSummary;

describe("CV export selection helpers", () => {
  it("normalizes an observation reference", () => {
    expect(observationToCvExportItem(observation)).toEqual({
      kind: "observation",
      cv_run_id: "run-1",
      observation_id: "obs-1",
    });
  });

  it("normalizes a candidate reference with unverified selection context", () => {
    expect(candidateToCvExportItem(candidate)).toEqual({
      kind: "candidate",
      cv_run_id: "run-2",
      observation_id: "obs-2",
      query_cv_run_id: "run-1",
      query_observation_id: "obs-1",
      candidate_id: "candidate-1",
      selection_context: {
        rank: 2,
        similarity_score: 0.91,
        score_meaning: "Cosine similarity; not identity.",
        candidate_disclaimer: CV_CANDIDATE_DISCLAIMER,
      },
    });
  });

  it("rejects path-like identifiers, invalid candidate context and non-integer ranks", () => {
    expect(normalizeCvExportItem({ kind: "observation", cv_run_id: "../run", observation_id: "obs-1" })).toBeNull();
    expect(normalizeCvExportItem({ kind: "observation", cv_run_id: "run-1", observation_id: "obs:1" })).toBeNull();
    expect(normalizeCvExportItem({
      kind: "candidate",
      cv_run_id: "run-2",
      observation_id: "obs-2",
      query_cv_run_id: "run-1",
      query_observation_id: "obs-1",
      selection_context: { rank: 1.5, similarity_score: 0.9 },
    })).toBeNull();
    expect(normalizeCvExportItem({
      kind: "candidate",
      cv_run_id: "run-2",
      observation_id: "obs-2",
      query_cv_run_id: "run-1",
    })).toBeNull();
  });

  it("parses only valid draft items and ignores malformed drafts", () => {
    const raw = JSON.stringify([
      { kind: "observation", cv_run_id: "run-1", observation_id: "obs-1" },
      { kind: "observation", cv_run_id: "../../run", observation_id: "obs-2" },
      { kind: "candidate", cv_run_id: "run-2", observation_id: "obs-3" },
    ]);
    expect(parseDraftCvItems(raw)).toEqual([{
      kind: "observation",
      cv_run_id: "run-1",
      observation_id: "obs-1",
    }]);
    expect(parseDraftCvItems("not-json")).toEqual([]);
    expect(parseDraftCvItems(null)).toEqual([]);
  });

  it("builds a legacy payload when no CV references are selected", () => {
    expect(buildExportPayload("case-1", ["frame-1"])).toEqual({
      case_id: "case-1",
      frame_ids: ["frame-1"],
    });
  });

  it("deduplicates selections and caps the payload", () => {
    const items = Array.from({ length: 26 }, (_, index) => ({
      kind: "observation",
      cv_run_id: "run-1",
      observation_id: `obs-${index}`,
    })) as CvExportItem[];
    const payload = buildExportPayload("case-1", ["frame-1"], [
      ...items,
      { kind: "observation", cv_run_id: "run-1", observation_id: "obs-0" },
    ]);
    expect(payload.cv_items).toHaveLength(25);
    expect(new Set(payload.cv_items?.map((item) => item.observation_id)).size).toBe(25);
  });
});
