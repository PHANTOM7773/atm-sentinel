import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { demoOptionLabel, isDemoCase, isDemoTransaction, isDemoVideo } from "./demo";
import { DemoBadge, DemoDataBanner } from "../components/ui";

describe("demo data labels", () => {
  it("detects demo markers in cases, clips, and transactions", () => {
    expect(isDemoCase({ case_number: "CASE-1", title: "Investigation", tags: "atm-01" })).toBe(false);
    expect(isDemoCase({ case_number: "DEMO-1", title: "Case", tags: "" })).toBe(true);
    expect(isDemoCase({ title: "Synthetic review", tags: "" })).toBe(true);
    expect(isDemoVideo({ original_filename: "sample.mp4" })).toBe(true);
    expect(isDemoTransaction({ reference: "TX-1", note: "test data" })).toBe(true);
  });

  it("labels demo records in select options", () => {
    expect(demoOptionLabel("CASE-1", false)).toBe("CASE-1");
    expect(demoOptionLabel("DEMO-1", true)).toContain("[demo data]");
  });

  it("renders visible demo warnings", () => {
    const badge = renderToStaticMarkup(createElement(DemoBadge));
    const banner = renderToStaticMarkup(createElement(DemoDataBanner, { subject: "case" }));
    expect(badge).toContain("Demo data");
    expect(banner).toContain("Do not treat it as genuine investigator material");
  });
});
