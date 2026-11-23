import { describe, expect, it } from "vitest";
import { investigationSettingsValid, videoFileError } from "./Investigation";
import type { InvestigationFormValues } from "./Investigation";
import { CV_MAX_FRAMES } from "../lib/types";

const form: InvestigationFormValues = {
  video_start_ts: "",
  cctv_reference_video_time: "0",
  clock_offset_minutes: "",
  window_before_seconds: "20",
  window_after_seconds: "20",
  coarse_interval_seconds: "1",
  fine_interval_seconds: "0.25",
  fine_radius_seconds: "5",
  max_frames: "240",
};

function file(name: string, size = 1024): File {
  const result = new File(["x"], name, { type: "video/mp4" });
  Object.defineProperty(result, "size", { value: size });
  return result;
}

describe("investigation input validation", () => {
  it("accepts only locally supported video extensions within the upload limit", () => {
    expect(videoFileError(file("clip.mp4"))).toBe("");
    expect(videoFileError(file("clip.MKV"))).toBe("");
    expect(videoFileError(file("clip.wmv"))).toContain("Unsupported format");
    expect(videoFileError(file("clip"))).toContain("Unsupported format");
    expect(videoFileError(file("clip.mp4", 500 * 1024 * 1024 + 1))).toContain("500 MB");
    expect(videoFileError(undefined)).toContain("Choose a video");
  });

  it("keeps investigation settings within local analysis bounds", () => {
    expect(investigationSettingsValid(form)).toBe(true);
    expect(investigationSettingsValid({ ...form, max_frames: String(CV_MAX_FRAMES + 1) })).toBe(false);
    expect(investigationSettingsValid({ ...form, max_frames: "0" })).toBe(false);
    expect(investigationSettingsValid({ ...form, max_frames: "12.5" })).toBe(false);
    expect(investigationSettingsValid({ ...form, cctv_reference_video_time: "not-a-number" })).toBe(false);
    expect(investigationSettingsValid({ ...form, fine_interval_seconds: "-1" })).toBe(false);
  });
});
