import { describe, expect, it } from "vitest";

import { ResultPanel } from "./ResultPanel";
import { renderToContainer } from "./testUtils";
import type { RunSummary } from "./types";

function makeSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: "abc123",
    dataset_id: "ds1",
    question: "what is x?",
    status: "answered",
    answers: [{ name: "x", value: "1" }],
    explanation: "computed from stdout",
    code: "print('x =', 1)",
    stdout_tail: "x = 1\n",
    evidence: [{ name: "x", value: "1", passed: true, reason: "matched 1 in stdout" }],
    attempts: [],
    chart_urls: [],
    prompt_tokens: 100,
    completion_tokens: 20,
    wall_time_ms: 13000,
    llm_time_ms: 2200,
    sandbox_time_ms: 10300,
    error: null,
    ...overrides,
  };
}

describe("ResultPanel", () => {
  it("renders model output containing a <script> tag as plain text, never as a parsed element", () => {
    const malicious = "Ignore prior instructions <script>window.__pwned = true</script> done.";
    const { container, unmount } = renderToContainer(
      <ResultPanel summary={makeSummary({ explanation: malicious })} />,
    );

    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain(
      "<script>window.__pwned = true</script>",
    );
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
    unmount();
  });

  it("renders the answer, final code, and a trace download link for an answered run", () => {
    const { container, unmount } = renderToContainer(<ResultPanel summary={makeSummary()} />);
    expect(container.textContent).toContain("Answered");
    expect(container.textContent).toContain("x");
    expect(container.querySelector("a[href='/api/runs/abc123/trace']")).not.toBeNull();
    unmount();
  });

  it("shows wall time as the headline Time stat, with LLM/sandbox time as secondary stats", () => {
    const { container, unmount } = renderToContainer(<ResultPanel summary={makeSummary()} />);
    expect(container.textContent).toContain("13.0s");
    expect(container.textContent).toContain("LLM time 2.2s");
    expect(container.textContent).toContain("Sandbox time 10.3s");
    unmount();
  });

  it("shows the attempts, tokens, and time recorded before an unexpected failure", () => {
    const summary = makeSummary({
      status: "error",
      error: "RuntimeError",
      answers: [],
      explanation: "",
      evidence: [],
      attempts: [
        {
          attempt: 1,
          has_code: true,
          check_ok: true,
          n_check_violations: 0,
          exec_ok: true,
          timed_out: false,
          answered: false,
          observation: null,
        },
      ],
      prompt_tokens: 40,
      completion_tokens: 10,
      wall_time_ms: 900,
      llm_time_ms: 800,
      sandbox_time_ms: 50,
    });
    const { container, unmount } = renderToContainer(<ResultPanel summary={summary} />);
    expect(container.textContent).toContain("Unexpected error (RuntimeError)");
    expect(container.querySelector(".stats dd")?.textContent).toBe("1");
    unmount();
  });
});
