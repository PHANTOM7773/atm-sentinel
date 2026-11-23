import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CvCropEnhancementPanel } from "./CvCropEnhancementPanel";
import { cvApi } from "../lib/api";
import type { CvEnhancedCropResult } from "../lib/types";

const presets = [
  { name: "general_enhancement", label: "General enhancement", description: "", params: {} },
  { name: "clarity_boost", label: "Clarity boost", description: "", params: {} },
];

const result: CvEnhancedCropResult = {
  original_path: "original.png",
  original_sha256: "a".repeat(64),
  enhanced_path: "enhanced.png",
  enhanced_sha256: "b".repeat(64),
  preset: "general_enhancement",
  preset_label: "General enhancement",
  params: {},
  method: "opencv",
  method_version: "1",
  derived_label: "derived",
  original_width: 100,
  original_height: 100,
  enhanced_width: 200,
  enhanced_height: 200,
  processing_ms: 12.5,
  metadata_path: "metadata.json",
  warnings: [],
  case_id: "case-1",
  cv_run_id: "run-1",
  observation_id: "obs-1",
  crop_id: "crop-1",
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  vi.spyOn(cvApi, "enhancementPresets").mockResolvedValue({ items: presets, derived_label: "derived" });
  vi.spyOn(cvApi, "enhanceCrop").mockResolvedValue(result);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function button(label: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll("button")).find((item) => item.textContent?.includes(label));
  if (!found) throw new Error(`Button not found: ${label}`);
  return found;
}

describe("CvCropEnhancementPanel", () => {
  it("clears a stale derived preview when the preset changes", async () => {
    await act(async () => {
      root.render(createElement(CvCropEnhancementPanel, {
        caseId: "case-1",
        runId: "run-1",
        observationId: "obs-1",
        cropId: "crop-1",
      }));
    });
    await flush();

    expect(container.textContent).not.toContain("Loading presets");
    await act(async () => { button("Enhance").click(); });
    await flush();
    expect(container.textContent).toContain("Enhanced (General enhancement)");

    const select = container.querySelector("select");
    if (!select) throw new Error("Preset select not found");
    await act(async () => {
      select.value = "clarity_boost";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(container.textContent).toContain("Run enhancement to generate derived preview");
    expect(container.textContent).not.toContain("Enhanced (General enhancement)");
    expect(cvApi.enhanceCrop).toHaveBeenCalledTimes(1);
  });
});
