import { describe, expect, it } from "vitest";

import budgetExceeded from "./fixtures/budget_exceeded.json";
import chartRun from "./fixtures/chart_run.json";
import checkerBlockRepair from "./fixtures/checker_block_repair.json";
import crashRepair from "./fixtures/crash_repair.json";
import errorRepairSuccess from "./fixtures/error_repair_success.json";
import happyPath from "./fixtures/happy_path.json";
import toolFailure from "./fixtures/tool_failure.json";
import { initialTimelineState, reduceTimeline, reduceTimelineAll } from "./timeline";
import type { AgentEvent } from "./types";

const FIXTURES = {
  happyPath: happyPath as AgentEvent[],
  errorRepairSuccess: errorRepairSuccess as AgentEvent[],
  checkerBlockRepair: checkerBlockRepair as AgentEvent[],
  crashRepair: crashRepair as AgentEvent[],
  toolFailure: toolFailure as AgentEvent[],
  budgetExceeded: budgetExceeded as AgentEvent[],
  chartRun: chartRun as AgentEvent[],
};

describe("reduceTimeline over real agent-loop fixtures", () => {
  it("happy path: one attempt, answered", () => {
    const state = reduceTimelineAll(FIXTURES.happyPath);
    expect(state.status).toBe("answered");
    expect(state.attempts).toHaveLength(1);
    expect(state.attempts[0].phase).toBe("answered");
    expect(state.attempts[0].evidence[0].passed).toBe(true);
  });

  it("error then repair then success: two attempts, first repairing", () => {
    const state = reduceTimelineAll(FIXTURES.errorRepairSuccess);
    expect(state.status).toBe("answered");
    expect(state.attempts).toHaveLength(2);
    expect(state.attempts[0].phase).toBe("repairing");
    expect(state.attempts[0].execResult?.error?.name).toBe("KeyError");
    expect(state.attempts[1].phase).toBe("answered");
  });

  it("checker block then repair: first attempt never reaches the sandbox", () => {
    const state = reduceTimelineAll(FIXTURES.checkerBlockRepair);
    expect(state.status).toBe("answered");
    expect(state.attempts).toHaveLength(2);
    expect(state.attempts[0].checkOk).toBe(false);
    expect(state.attempts[0].violations.length).toBeGreaterThan(0);
    expect(state.attempts[0].execResult).toBeNull();
    expect(state.attempts[1].phase).toBe("answered");
  });

  it("crash then repair then success: first attempt's exec result is a crash", () => {
    const state = reduceTimelineAll(FIXTURES.crashRepair);
    expect(state.status).toBe("answered");
    expect(state.attempts).toHaveLength(2);
    expect(state.attempts[0].execResult?.crashed).toBe(true);
    expect(state.attempts[1].phase).toBe("answered");
  });

  it("two crashes in a row: tool_failure, no attempt ever answers", () => {
    const state = reduceTimelineAll(FIXTURES.toolFailure);
    expect(state.status).toBe("tool_failure");
    expect(state.attempts).toHaveLength(2);
    expect(state.attempts.every((a) => a.phase !== "answered")).toBe(true);
  });

  it("token budget exceeded: the one started attempt never finishes writing code", () => {
    const state = reduceTimelineAll(FIXTURES.budgetExceeded);
    expect(state.status).toBe("budget_exceeded");
    expect(state.attempts).toHaveLength(1);
    expect(state.attempts[0].phase).toBe("writing_code");
    expect(state.attempts[0].code).toBeNull();
  });

  it("a chart run: the exec result carries one image", () => {
    const state = reduceTimelineAll(FIXTURES.chartRun);
    expect(state.status).toBe("answered");
    expect(state.attempts[0].execResult?.images).toHaveLength(1);
  });
});

describe("reduceTimeline robustness: duplicates and out-of-order delivery", () => {
  it("re-applying the exact same events (an SSE replay) is a no-op", () => {
    const events = FIXTURES.errorRepairSuccess;
    const once = reduceTimelineAll(events);
    const twice = reduceTimelineAll([...events, ...events]);
    expect(twice).toEqual(once);
  });

  it("re-applying a single duplicated event changes nothing", () => {
    const events = FIXTURES.happyPath;
    const withDuplicate = [events[0], events[0], ...events.slice(1)];
    expect(reduceTimelineAll(withDuplicate)).toEqual(reduceTimelineAll(events));
  });

  it("feeding events in fully reversed order converges to the same final state", () => {
    const events = FIXTURES.errorRepairSuccess;
    const forward = reduceTimelineAll(events);
    const backward = reduceTimelineAll([...events].reverse());
    expect(backward.status).toBe(forward.status);
    expect(backward.attempts).toEqual(forward.attempts);
  });

  it("an attempt's phase never regresses once a later-ranked event is applied", () => {
    const events = FIXTURES.happyPath;
    const evidenceEvent = events.find((e) => e.type === "evidence");
    if (evidenceEvent === undefined) {
      throw new Error("fixture has no evidence event");
    }
    const codeEvent = events.find((e) => e.type === "code");
    if (codeEvent === undefined) {
      throw new Error("fixture has no code event");
    }
    // Apply the evidence event (which drives the attempt to "answered")
    // before its own earlier "code" event arrives.
    let state = reduceTimeline(initialTimelineState, evidenceEvent);
    state = reduceTimeline(state, codeEvent);
    expect(state.attempts[0].phase).toBe("answered");
  });

  it("an unknown seq a run never emitted is simply ignored by later real events", () => {
    const events = FIXTURES.happyPath;
    let state = initialTimelineState;
    for (const event of events) {
      state = reduceTimeline(state, event);
    }
    const sameSeqAgain = reduceTimeline(state, events[0]);
    expect(sameSeqAgain).toEqual(state);
  });
});
