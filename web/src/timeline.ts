/**
 * A pure reducer: AgentEvent in, UI timeline state out. No side effects, no
 * network -- fed either by `useRunEvents` (live) or a fixture array (tests),
 * which is what lets the fixtures exported by
 * `scripts/export_ui_fixtures.py` double as the reducer's test suite.
 *
 * Deliberately defensive about its own input, not just its caller: a
 * duplicate `seq` is a no-op, and applying events out of `seq` order can
 * never move an attempt's `phase` backwards (see `advancePhase`).
 */

import type {
  AgentEvent,
  AnswerPayload,
  CodePayload,
  EvidenceItem,
  EvidencePayload,
  ExecResultPayload,
  ObservationPayload,
  ProfilePayload,
  RunFinishedPayload,
  RunStartedPayload,
  StaticCheckPayload,
  Violation,
} from "./types";

export type AttemptPhase =
  | "writing_code"
  | "checked"
  | "running"
  | "result"
  | "repairing"
  | "answered";

const PHASE_RANK: Record<AttemptPhase, number> = {
  writing_code: 1,
  checked: 2,
  running: 3,
  result: 4,
  repairing: 5,
  answered: 6,
};

export type RunStatus =
  | "idle"
  | "running"
  | "answered"
  | "failed"
  | "repeated_failure"
  | "tool_failure"
  | "budget_exceeded"
  | "llm_error"
  | "error";

export interface AttemptState {
  attempt: number;
  phase: AttemptPhase;
  code: string | null;
  checkOk: boolean | null;
  violations: Violation[];
  execResult: ExecResultPayload | null;
  observation: string | null;
  answer: AnswerPayload | null;
  evidence: EvidenceItem[];
  startedAt: number;
  updatedAt: number;
  /** Every raw event seen for this attempt, seq-ordered -- for elapsed-time display. */
  events: AgentEvent[];
}

export interface TimelineState {
  runId: string | null;
  status: RunStatus;
  runStarted: RunStartedPayload | null;
  profile: ProfilePayload | null;
  attempts: AttemptState[];
  finished: RunFinishedPayload | null;
  seenSeqs: ReadonlySet<number>;
}

export const initialTimelineState: TimelineState = {
  runId: null,
  status: "idle",
  runStarted: null,
  profile: null,
  attempts: [],
  finished: null,
  seenSeqs: new Set(),
};

function advancePhase(current: AttemptPhase, next: AttemptPhase): AttemptPhase {
  return PHASE_RANK[next] >= PHASE_RANK[current] ? next : current;
}

function insertEvent(events: AgentEvent[], event: AgentEvent): AgentEvent[] {
  if (events.some((e) => e.seq === event.seq)) {
    return events;
  }
  return [...events, event].sort((a, b) => a.seq - b.seq);
}

function withAttempt(
  attempts: AttemptState[],
  attemptN: number,
  ts: number,
  event: AgentEvent,
  update: (attempt: AttemptState) => AttemptState,
): AttemptState[] {
  const index = attempts.findIndex((a) => a.attempt === attemptN);
  const base: AttemptState =
    index === -1
      ? {
          attempt: attemptN,
          phase: "writing_code",
          code: null,
          checkOk: null,
          violations: [],
          execResult: null,
          observation: null,
          answer: null,
          evidence: [],
          startedAt: ts,
          updatedAt: ts,
          events: [],
        }
      : attempts[index];

  const updated: AttemptState = {
    ...update(base),
    updatedAt: ts,
    events: insertEvent(base.events, event),
  };

  if (index === -1) {
    return [...attempts, updated].sort((a, b) => a.attempt - b.attempt);
  }
  const next = [...attempts];
  next[index] = updated;
  return next;
}

export function reduceTimeline(state: TimelineState, event: AgentEvent): TimelineState {
  if (state.seenSeqs.has(event.seq)) {
    return state;
  }
  const seenSeqs = new Set(state.seenSeqs);
  seenSeqs.add(event.seq);
  const base: TimelineState = { ...state, seenSeqs };

  switch (event.type) {
    case "run_started": {
      const payload = event.payload as unknown as RunStartedPayload;
      // Guard against a `run_started` applied after `run_finished` has
      // already been seen (possible under out-of-order delivery) so it
      // can never clobber a terminal status back to "running".
      const status = state.finished !== null ? state.status : "running";
      return { ...base, runId: event.run_id, status, runStarted: payload };
    }

    case "profile": {
      return { ...base, profile: event.payload as unknown as ProfilePayload };
    }

    case "run_finished": {
      const payload = event.payload as unknown as RunFinishedPayload;
      let attempts = state.attempts;
      if (payload.status === "answered" && attempts.length > 0) {
        const lastIndex = attempts.length - 1;
        attempts = attempts.map((a, i) =>
          i === lastIndex ? { ...a, phase: advancePhase(a.phase, "answered") } : a,
        );
      }
      return { ...base, status: payload.status as RunStatus, finished: payload, attempts };
    }

    case "llm_request": {
      return {
        ...base,
        attempts: withAttempt(state.attempts, event.attempt, event.ts, event, (a) => ({
          ...a,
          phase: advancePhase(a.phase, "writing_code"),
        })),
      };
    }

    case "llm_response": {
      return {
        ...base,
        attempts: withAttempt(state.attempts, event.attempt, event.ts, event, (a) => a),
      };
    }

    case "code": {
      const payload = event.payload as unknown as CodePayload;
      return {
        ...base,
        attempts: withAttempt(state.attempts, event.attempt, event.ts, event, (a) => ({
          ...a,
          code: payload.code,
          phase: advancePhase(a.phase, "writing_code"),
        })),
      };
    }

    case "static_check": {
      const payload = event.payload as unknown as StaticCheckPayload;
      return {
        ...base,
        attempts: withAttempt(state.attempts, event.attempt, event.ts, event, (a) => ({
          ...a,
          checkOk: payload.ok,
          violations: payload.violations,
          phase: advancePhase(a.phase, "checked"),
        })),
      };
    }

    case "exec_started": {
      return {
        ...base,
        attempts: withAttempt(state.attempts, event.attempt, event.ts, event, (a) => ({
          ...a,
          phase: advancePhase(a.phase, "running"),
        })),
      };
    }

    case "exec_result": {
      const payload = event.payload as unknown as ExecResultPayload;
      return {
        ...base,
        attempts: withAttempt(state.attempts, event.attempt, event.ts, event, (a) => ({
          ...a,
          execResult: payload,
          phase: advancePhase(a.phase, "result"),
        })),
      };
    }

    case "answer": {
      const payload = event.payload as unknown as AnswerPayload;
      return {
        ...base,
        attempts: withAttempt(state.attempts, event.attempt, event.ts, event, (a) => ({
          ...a,
          answer: payload,
        })),
      };
    }

    case "evidence": {
      const payload = event.payload as unknown as EvidencePayload;
      const allPassed = payload.results.length > 0 && payload.results.every((r) => r.passed);
      return {
        ...base,
        attempts: withAttempt(state.attempts, event.attempt, event.ts, event, (a) => ({
          ...a,
          evidence: payload.results,
          phase: allPassed ? advancePhase(a.phase, "answered") : a.phase,
        })),
      };
    }

    case "observation": {
      const payload = event.payload as unknown as ObservationPayload;
      return {
        ...base,
        attempts: withAttempt(state.attempts, event.attempt, event.ts, event, (a) => ({
          ...a,
          observation: payload.text,
          phase: advancePhase(a.phase, "repairing"),
        })),
      };
    }

    default:
      return base;
  }
}

export function reduceTimelineAll(events: AgentEvent[]): TimelineState {
  return events.reduce(reduceTimeline, initialTimelineState);
}
