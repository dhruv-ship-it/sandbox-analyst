import { useEffect, useMemo, useState } from "react";

import { ApiRequestError, createRun, getHealth, getRun } from "./api";
import { DataStep } from "./DataStep";
import { Footer } from "./Footer";
import { Header } from "./Header";
import { HowItWorks } from "./HowItWorks";
import { QuestionStep } from "./QuestionStep";
import { ResultPanel } from "./ResultPanel";
import { Timeline } from "./TimelineView";
import { reduceTimelineAll } from "./timeline";
import type { DatasetSummary, HealthResponse, RunSummary } from "./types";
import { useRunEvents } from "./useRunEvents";

const TERMINAL_STATUSES = new Set([
  "answered",
  "failed",
  "repeated_failure",
  "tool_failure",
  "budget_exceeded",
  "llm_error",
  "error",
]);

export default function App(): JSX.Element {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [dataset, setDataset] = useState<DatasetSummary | null>(null);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [summary, setSummary] = useState<RunSummary | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => undefined);
  }, []);

  const events = useRunEvents(runId);
  const timeline = useMemo(() => reduceTimelineAll(events), [events]);
  const running = runId !== null && !TERMINAL_STATUSES.has(timeline.status);

  useEffect(() => {
    if (runId === null || !TERMINAL_STATUSES.has(timeline.status)) {
      return undefined;
    }
    let cancelled = false;
    getRun(runId)
      .then((body) => {
        if (!cancelled) {
          setSummary(body);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [runId, timeline.status]);

  function handleDatasetLoaded(loaded: DatasetSummary, questions: string[]): void {
    setDataset(loaded);
    setSuggestedQuestions(questions);
    setRunId(null);
    setSummary(null);
    setRunError(null);
    setQuestion("");
  }

  async function handleRun(): Promise<void> {
    if (dataset === null) {
      return;
    }
    setRunError(null);
    setSummary(null);
    try {
      const response = await createRun(dataset.dataset_id, question);
      setRunId(response.run_id);
    } catch (err) {
      setRunError(err instanceof ApiRequestError ? err.message : "Could not start the run.");
    }
  }

  const canRun = dataset !== null && question.length >= 3 && question.length <= 500 && !running;

  return (
    <>
      <Header />
      <main>
        <HowItWorks health={health} />
        <DataStep dataset={dataset} onLoaded={handleDatasetLoaded} disabled={running} />
        <QuestionStep
          question={question}
          onQuestionChange={setQuestion}
          suggestedQuestions={suggestedQuestions}
          onRun={() => void handleRun()}
          canRun={canRun}
          running={running}
          runError={runError}
        />
        {timeline.attempts.length > 0 && (
          <section aria-labelledby="timeline-heading" className="step-section">
            <h2 id="timeline-heading">Live run</h2>
            <Timeline attempts={timeline.attempts} />
          </section>
        )}
        {summary !== null && <ResultPanel summary={summary} />}
      </main>
      <Footer health={health} />
    </>
  );
}
