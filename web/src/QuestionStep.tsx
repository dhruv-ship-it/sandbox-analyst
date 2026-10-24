const MIN_LEN = 3;
const MAX_LEN = 500;

interface QuestionStepProps {
  question: string;
  onQuestionChange: (question: string) => void;
  suggestedQuestions: string[];
  onRun: () => void;
  canRun: boolean;
  running: boolean;
  runError: string | null;
}

export function QuestionStep({
  question,
  onQuestionChange,
  suggestedQuestions,
  onRun,
  canRun,
  running,
  runError,
}: QuestionStepProps): JSX.Element {
  return (
    <section aria-labelledby="question-step-heading" className="step-section">
      <h2 id="question-step-heading">2. Ask a question</h2>

      {suggestedQuestions.length > 0 && (
        <div className="suggested-questions">
          <p>Suggestions:</p>
          <ul>
            {suggestedQuestions.map((suggestion) => (
              <li key={suggestion}>
                <button
                  type="button"
                  className="chip"
                  disabled={running}
                  onClick={() => onQuestionChange(suggestion)}
                >
                  {suggestion}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <label htmlFor="question-input">Your question</label>
      <textarea
        id="question-input"
        value={question}
        rows={3}
        minLength={MIN_LEN}
        maxLength={MAX_LEN}
        disabled={running}
        placeholder="e.g. Which product has the highest average unit price?"
        onChange={(event) => onQuestionChange(event.target.value)}
      />
      <p className="char-counter">
        {question.length}/{MAX_LEN}
      </p>

      {runError !== null && (
        <p role="alert" className="error-message">
          {runError}
        </p>
      )}

      <button type="button" onClick={onRun} disabled={!canRun || running}>
        {running ? "Running…" : "Run"}
      </button>
    </section>
  );
}
