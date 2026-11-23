import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("api.download", () => {
  it("uses a transient anchor instead of a popup window", () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    const clicked: HTMLAnchorElement[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this);
    });

    api.download("/api/exports/report-1/pdf");

    expect(open).not.toHaveBeenCalled();
    expect(click).toHaveBeenCalledTimes(1);
    expect(clicked[0]?.getAttribute("href")).toContain("/api/exports/report-1/pdf");
    expect(document.body.querySelector("a")).toBeNull();
  });
});
