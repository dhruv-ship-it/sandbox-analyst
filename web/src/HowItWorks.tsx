import type { HealthResponse } from "./types";

export function HowItWorks({ health }: { health: HealthResponse | null }): JSX.Element {
  return (
    <details className="how-it-works" id="how-it-works">
      <summary>How it works</summary>
      <div className="how-it-works-body">
        <p>
          You ask a question about a CSV. A language model writes a Python script to answer it,
          the script is checked for obviously unsafe code, then it runs inside an isolated
          sandbox. If it fails, the model sees what went wrong and tries again, up to a few
          times. Every answer is checked against the script&apos;s own printed output before it
          is shown as verified.
        </p>
        <h3>Trust boundaries</h3>
        <ul>
          <li>The sandbox has no network access and runs under gVisor, a second isolation layer below the usual kernel sandboxing.</li>
          <li>Every script is statically checked before it runs, as a fast first line of defense.</li>
          <li>Only a short column summary and five sample rows of your data are ever sent to the language model -- never the whole file.</li>
          <li>Uploaded files are deleted after one hour.</li>
        </ul>
        {health !== null && (
          <p>
            Currently running <strong>{health.model}</strong> via <strong>{health.provider}</strong>.
          </p>
        )}
      </div>
    </details>
  );
}
