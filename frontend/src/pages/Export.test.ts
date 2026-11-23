import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ExportPage,
  buildExportPayload,
  candidateToCvExportItem,
  normalizeCvExportItem,
  observationToCvExportItem,
  parseDraftCvItems,
} from "./Export";
import { CV_CANDIDATE_DISCLAIMER } from "../lib/types";
import type { CaseRecord, CvCandidateSummary, CvExportItem, CvFaceObservationSummary, ExportRecord, FrameRecord } from "../lib/types";

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

const cases: CaseRecord[] = [
  {
    id: "case-1",
    case_number: "CASE-1",
    title: "First case",
    location: "ATM-1",
    tags: "",
    status: "active",
    created_at: "2026-11-22T00:00:00Z",
    updated_at: "2026-11-22T00:00:00Z",
  },
  {
    id: "case-2",
    case_number: "CASE-2",
    title: "Second case",
    location: "ATM-2",
    tags: "",
    status: "active",
    created_at: "2026-11-22T00:00:00Z",
    updated_at: "2026-11-22T00:00:00Z",
  },
];

function frame(caseId: string): FrameRecord {
  return {
    id: `frame-${caseId}`,
    job_id: `job-${caseId}`,
    video_id: `video-${caseId}`,
    case_id: caseId,
    frame_number: 1,
    timestamp: 1,
    relative_time: 1,
    image_path: "image.png",
    thumb_path: "thumb.png",
    sha256: "a".repeat(64),
    sharpness: 50,
    brightness: 100,
    contrast: 40,
    quality_score: 80,
    warnings: [],
    metrics: {},
    source: "coarse",
    created_at: "2026-11-22T00:00:00Z",
    selected: true,
    selection_note: "",
    selection_reason: "",
    frame_notes: [],
  };
}

const exportRecord: ExportRecord = {
  id: "export-1",
  case_id: "case-1",
  frame_count: 1,
  report_hash: "b".repeat(64),
  pdf_path: "exports/report-1.pdf",
  pdf_sha256: "c".repeat(64),
  manifest_path: "exports/report-1.json",
  created_at: "2026-11-22T00:00:00Z",
};

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    statusText: "OK",
    headers: { "Content-Type": "application/json" },
  });
}

describe("ExportPage generated report state", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    window.sessionStorage.clear();
    vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/cases")) return json(cases);
      if (url.includes("/api/frames")) return json([frame(url.includes("case-2") ? "case-2" : "case-1")]);
      if (url.includes("/api/exports?")) return json([]);
      if (url.includes("/api/cv/runs")) return json({ items: [], total: 0, limit: 25, offset: 0 });
      if (url.includes("/api/exports") && init?.method === "POST") return json(exportRecord);
      return json({});
    }));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  async function flush(): Promise<void> {
    for (let index = 0; index < 6; index += 1) {
      await act(async () => { await Promise.resolve(); });
    }
  }

  function findButton(label: string): HTMLButtonElement {
    const found = Array.from(container.querySelectorAll("button")).find((item) => item.textContent?.includes(label));
    if (!found) throw new Error(`Button not found: ${label}`);
    return found;
  }

  it("keeps generated report details with their case and frame selection", async () => {
    await act(async () => {
      root.render(createElement(MemoryRouter, { initialEntries: ["/export?case=case-1"] }, createElement(ExportPage)));
    });
    await flush();

    await act(async () => { findButton("Generate PDF report").click(); });
    await flush();
    expect(container.textContent).toContain("Report data SHA-256");
    expect(container.textContent).toContain("uses the 1 frame(s) included in the generated report");

    const select = container.querySelector("select");
    if (!select) throw new Error("Case select not found");
    await act(async () => {
      select.value = "case-2";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flush();
    expect(container.textContent).not.toContain("Report data SHA-256");
  });
});
