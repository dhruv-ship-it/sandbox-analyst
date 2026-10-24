import type { ExecResultPayload } from "./types";

export function ExecResultView({ result }: { result: ExecResultPayload }): JSX.Element {
  if (result.crashed === true) {
    return <p className="exec-crashed">The sandbox crashed: {String(result.error)}</p>;
  }
  if (result.unavailable === true) {
    return <p className="exec-crashed">The sandbox was unavailable: {String(result.error)}</p>;
  }
  const images = result.images ?? [];
  const structuredError =
    result.error != null && typeof result.error === "object" ? result.error : null;
  return (
    <div>
      {result.timed_out === true && (
        <p className="exec-timeout">Timed out after the configured limit.</p>
      )}
      {structuredError !== null && (
        <p className="exec-error">
          {structuredError.name}: {structuredError.value}
        </p>
      )}
      {images.length > 0 && (
        <p className="exec-images">
          {images.length} chart{images.length === 1 ? "" : "s"} captured.
        </p>
      )}
      <details className="stdout-details">
        <summary>stdout / stderr</summary>
        <pre className="plain-pre">{result.stdout === "" || result.stdout === undefined ? "(empty)" : result.stdout}</pre>
        {result.stderr !== undefined && result.stderr !== "" && (
          <pre className="plain-pre stderr">{result.stderr}</pre>
        )}
      </details>
    </div>
  );
}
