import type { HealthResponse } from "./types";

export function Footer({ health }: { health: HealthResponse | null }): JSX.Element {
  return (
    <footer className="app-footer">
      <p>
        Demo limits: up to 5 runs per hour and 20 per day per visitor; 50 runs per day total
        across everyone.
      </p>
      <p>
        Privacy: please don&apos;t upload sensitive data. Only a column summary and five sample
        rows are ever sent to the language model provider.
      </p>
      {health !== null && <p className="version-tag">version {health.version}</p>}
    </footer>
  );
}
