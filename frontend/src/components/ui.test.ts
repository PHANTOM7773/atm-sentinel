import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Modal } from "./ui";

describe("Modal accessibility", () => {
  it("exposes a labelled dialog and hides when closed", () => {
    const open = renderToStaticMarkup(createElement(Modal, {
      open: true,
      onClose: () => undefined,
      title: "Review details",
      children: createElement("p", null, "Detail content"),
    }));
    expect(open).toContain('role="dialog"');
    expect(open).toContain('aria-modal="true"');
    expect(open).toContain('aria-labelledby=');
    expect(open).toContain("Review details");
    expect(open).toContain("Detail content");

    expect(renderToStaticMarkup(createElement(Modal, {
      open: false,
      onClose: () => undefined,
      title: "Hidden",
      children: null,
    }))).toBe("");
  });
});
