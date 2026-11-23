import { describe, expect, it } from "vitest";
import { formatBytes, formatSeconds, qualityTone, statusTone } from "./format";
import { qs } from "./api";

describe("formatting helpers", () => {
  it("formats seconds without fabricating hours", () => {
    expect(formatSeconds(6)).toBe("00:06.00");
    expect(formatSeconds(3661.5)).toBe("01:01:01.50");
    expect(formatSeconds(undefined)).toBe("—");
  });

  it("formats byte sizes", () => {
    expect(formatBytes(0)).toBe("—");
    expect(formatBytes(1024)).toBe("1.0 KB");
  });

  it("returns readable tones", () => {
    expect(qualityTone(90)).toContain("ok");
    expect(statusTone("failed")).toContain("bad");
  });
});

describe("query strings", () => {
  it("omits empty values and encodes ids", () => {
    expect(qs({ case_id: "abc", video_id: "", job_id: undefined })).toBe("?case_id=abc");
    expect(qs({ ids: "a,b" })).toBe("?ids=a%2Cb");
  });
});
