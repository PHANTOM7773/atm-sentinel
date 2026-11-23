import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ComparePage } from "./Compare";
import { DashboardPage } from "./Dashboard";
import { EvidencePage } from "./Evidence";
import { ExportPage } from "./Export";
import { InvestigationPage } from "./Investigation";
import { WorkspacePage } from "./Workspace";
import { CV_ASSOCIATION_LIMITATION } from "../lib/types";

function render(node: Parameters<typeof renderToStaticMarkup>[0]): string {
  return renderToStaticMarkup(createElement(MemoryRouter, { initialEntries: ["/"] }, node));
}

describe("trust and interpretation copy", () => {
  it("labels dashboard counts as local records that can include demo data", () => {
    const html = render(createElement(DashboardPage));
    expect(html).toContain("including demo/sample records when present");
    expect(html).toContain("not operational statistics");
    expect(html).toContain("identity conclusions are not produced");
    expect(html).toContain(CV_ASSOCIATION_LIMITATION);
    expect(html).not.toContain("No operational statistics are simulated");
  });

  it("separates manual review from CV candidate search", () => {
    const investigation = render(createElement(InvestigationPage));
    const workspace = render(createElement(WorkspacePage));
    const evidence = render(createElement(EvidencePage));
    const compare = render(createElement(ComparePage));
    expect(investigation).toContain("CV embedding similarity ranks candidates only");
    expect(investigation).toContain(CV_ASSOCIATION_LIMITATION);
    expect(workspace).toContain("does not perform face detection or CV similarity ranking");
    expect(evidence).toContain("CV candidate search is separate");
    expect(compare).toContain("no automated identity matching");
    expect(compare).toContain("does not run face detection or compute similarity");
  });

  it("keeps CV candidate results opt-in in generated reports", () => {
    const html = render(createElement(ExportPage));
    expect(html).toContain("No CV candidate results are included unless you explicitly select them");
    expect(html).toContain("must not be represented as identity confirmation");
    expect(html).toContain("Optional CV references");
    expect(html).toContain(CV_ASSOCIATION_LIMITATION);
  });
});
