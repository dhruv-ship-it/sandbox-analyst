import { CodeBlock } from "./CodeBlock";
import { DiffView } from "./DiffView";
import { EvidenceList } from "./EvidenceList";
import { ExecResultView } from "./ExecResultView";
import type { AttemptPhase, AttemptState } from "./timeline";
import type { AgentEvent } from "./types";
import { formatElapsed } from "./utils";

const PHASE_LABELS: Record<AttemptPhase, string> = {
  writing_code: "Writing code",
  checked: "Checked",
  running: "Running",
  result: "Ran",
  repairing: "Repairing",
  answered: "Answered",
};

function PhaseBadge({ phase }: { phase: AttemptPhase }): JSX.Element {
  return <span className={`phase-badge phase-${phase}`}>{PHASE_LABELS[phase]}</span>;
}

function TimeTag({ event, startedAt }: { event: AgentEvent | undefined; startedAt: number }): JSX.Element | null {
  if (event === undefined) {
    return null;
  }
  return <span className="time-tag">+{formatElapsed((event.ts - startedAt) * 1000)}</span>;
}

function findEvent(events: AgentEvent[], type: AgentEvent["type"]): AgentEvent | undefined {
  return events.find((e) => e.type === type);
}

export function AttemptCard({
  attempt,
  previousCode,
}: {
  attempt: AttemptState;
  previousCode: string | null;
}): JSX.Element {
  const codeEvent = findEvent(attempt.events, "code");
  const checkEvent = findEvent(attempt.events, "static_check");
  const execStartedEvent = findEvent(attempt.events, "exec_started");
  const execResultEvent = findEvent(attempt.events, "exec_result");
  const observationEvent = findEvent(attempt.events, "observation");
  const answerEvent = findEvent(attempt.events, "answer");
  const isRepair = previousCode !== null;

  return (
    <li className="attempt-card">
      <div className="attempt-card-header">
        <h3>Attempt {attempt.attempt}</h3>
        <PhaseBadge phase={attempt.phase} />
      </div>

      {attempt.code === null && attempt.phase === "writing_code" && (
        <p className="step-pending">Writing code…</p>
      )}

      {attempt.code !== null && (
        <div className="step">
          <h4>
            {isRepair ? "Repaired code" : "Code"} <TimeTag event={codeEvent} startedAt={attempt.startedAt} />
          </h4>
          {isRepair && previousCode !== null ? (
            <DiffView previousCode={previousCode} nextCode={attempt.code} />
          ) : (
            <CodeBlock code={attempt.code} collapsible defaultCollapsed={false} />
          )}
        </div>
      )}

      {attempt.checkOk !== null && (
        <div className="step">
          <h4>
            Static check <TimeTag event={checkEvent} startedAt={attempt.startedAt} />
          </h4>
          {attempt.checkOk ? (
            <p className="check-pass">Passed.</p>
          ) : (
            <ul className="violations">
              {attempt.violations.map((violation, index) => (
                <li key={index}>
                  <code>{violation.rule_id}</code> (line {violation.line}): {violation.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {execStartedEvent !== undefined && (
        <div className="step">
          <h4>
            Running{" "}
            {attempt.execResult === null ? (
              <TimeTag event={execStartedEvent} startedAt={attempt.startedAt} />
            ) : (
              <TimeTag event={execResultEvent} startedAt={attempt.startedAt} />
            )}
          </h4>
          {attempt.execResult === null ? (
            <p className="step-pending">Running in the sandbox…</p>
          ) : (
            <ExecResultView result={attempt.execResult} />
          )}
        </div>
      )}

      {attempt.observation !== null && (
        <div className="step step-observation">
          <h4>
            Repair note <TimeTag event={observationEvent} startedAt={attempt.startedAt} />
          </h4>
          <p className="observation-text">{attempt.observation}</p>
        </div>
      )}

      {attempt.answer !== null && (
        <div className="step">
          <h4>
            Answer <TimeTag event={answerEvent} startedAt={attempt.startedAt} />
          </h4>
          <dl className="answer-list">
            {attempt.answer.answers.map((item) => (
              <div key={item.name} className="answer-row">
                <dt>{item.name}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
          <p className="answer-explanation">{attempt.answer.explanation}</p>
          <EvidenceList items={attempt.evidence} />
        </div>
      )}
    </li>
  );
}
