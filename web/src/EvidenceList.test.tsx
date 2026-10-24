import { describe, expect, it } from "vitest";

import { EvidenceList } from "./EvidenceList";
import { renderToContainer } from "./testUtils";

describe("EvidenceList", () => {
  it("renders a Verified badge for a passing item and a Not found badge for a failing one", () => {
    const { container, unmount } = renderToContainer(
      <EvidenceList
        items={[
          { name: "mean_x", value: "2.0", passed: true, reason: "matched 2.0 in stdout" },
          { name: "max_y", value: "9", passed: false, reason: "not found in stdout" },
        ]}
      />,
    );
    const items = container.querySelectorAll("li.evidence-item");
    expect(items).toHaveLength(2);
    expect(items[0].className).toContain("evidence-pass");
    expect(items[0].textContent).toContain("Verified");
    expect(items[1].className).toContain("evidence-fail");
    expect(items[1].textContent).toContain("Not found");
    unmount();
  });

  it("renders nothing for an empty list", () => {
    const { container, unmount } = renderToContainer(<EvidenceList items={[]} />);
    expect(container.textContent).toBe("");
    unmount();
  });
});
