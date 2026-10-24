import { describe, expect, it } from "vitest";

import App from "./App";
import { renderToContainer } from "./testUtils";

describe("App", () => {
  it("renders the heading", () => {
    const { container, unmount } = renderToContainer(<App />);
    expect(container.textContent).toContain("Sandbox Analyst");
    unmount();
  });
});
