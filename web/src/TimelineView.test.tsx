import { describe, expect, it } from "vitest";

import errorRepairSuccess from "./fixtures/error_repair_success.json";
import happyPath from "./fixtures/happy_path.json";
import { renderToContainer } from "./testUtils";
import { reduceTimelineAll } from "./timeline";
import { Timeline } from "./TimelineView";
import type { AgentEvent } from "./types";

describe("Timeline", () => {
  it("renders one attempt card for the happy-path fixture", () => {
    const state = reduceTimelineAll(happyPath as AgentEvent[]);
    const { container, unmount } = renderToContainer(<Timeline attempts={state.attempts} />);
    expect(container.querySelectorAll("li.attempt-card")).toHaveLength(1);
    expect(container.textContent).toContain("Attempt 1");
    expect(container.textContent).toContain("Answered");
    unmount();
  });

  it("renders two attempt cards for the error-repair-success fixture, with a diff for the repair", () => {
    const state = reduceTimelineAll(errorRepairSuccess as AgentEvent[]);
    const { container, unmount } = renderToContainer(<Timeline attempts={state.attempts} />);
    expect(container.querySelectorAll("li.attempt-card")).toHaveLength(2);
    expect(container.textContent).toContain("Attempt 1");
    expect(container.textContent).toContain("Attempt 2");
    expect(container.querySelector(".diff-view")).not.toBeNull();
    unmount();
  });
});
