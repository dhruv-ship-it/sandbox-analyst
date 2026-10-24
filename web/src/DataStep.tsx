import { useEffect, useRef, useState } from "react";

import { ApiRequestError, loadExample, listExamples, uploadDataset } from "./api";
import type { DatasetSummary, ExamplesResponse } from "./types";

const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

function validateFile(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".csv")) {
    return "Please choose a .csv file.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `That file is ${(file.size / (1024 * 1024)).toFixed(1)} MB, over the 5 MB limit.`;
  }
  return null;
}

interface DataStepProps {
  dataset: DatasetSummary | null;
  onLoaded: (dataset: DatasetSummary, suggestedQuestions: string[]) => void;
  disabled?: boolean;
}

export function DataStep({ dataset, onLoaded, disabled = false }: DataStepProps): JSX.Element {
  const [examples, setExamples] = useState<ExamplesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    listExamples()
      .then((data) => {
        if (!cancelled) {
          setExamples(data);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setExamples({});
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleFile(file: File): Promise<void> {
    const validationError = validateFile(file);
    if (validationError !== null) {
      setError(validationError);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const summary = await uploadDataset(file);
      onLoaded(summary, []);
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Upload failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function handleLoadExample(name: string): Promise<void> {
    if (examples === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const summary = await loadExample(name);
      onLoaded(summary, examples[name]?.questions ?? []);
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not load that example.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="data-step-heading" className="step-section">
      <h2 id="data-step-heading">1. Choose a dataset</h2>

      <div
        className={`dropzone ${dragActive ? "dropzone-active" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragActive(false);
          const file = event.dataTransfer.files[0];
          if (file !== undefined) {
            void handleFile(file);
          }
        }}
      >
        <p>Drag a .csv file here, or</p>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || busy}
        >
          Choose a file
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv"
          className="visually-hidden"
          aria-label="Choose a CSV file"
          disabled={disabled || busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file !== undefined) {
              void handleFile(file);
            }
            event.target.value = "";
          }}
        />
        <p className="hint">CSV only, up to 5 MB.</p>
      </div>

      {error !== null && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}

      {examples !== null && Object.keys(examples).length > 0 && (
        <div className="example-cards">
          <p>Or try an example:</p>
          <ul>
            {Object.entries(examples).map(([name, info]) => (
              <li key={name} className="example-card">
                <h3>{info.title}</h3>
                <p>{info.description}</p>
                <button
                  type="button"
                  onClick={() => void handleLoadExample(name)}
                  disabled={disabled || busy}
                >
                  Load {info.title}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {dataset !== null && (
        <div className="dataset-preview">
          <h3>{dataset.file_name}</h3>
          <p>
            {dataset.n_rows} rows &times; {dataset.n_cols} columns
          </p>
          <ul className="column-list">
            {dataset.columns.map((column) => (
              <li key={column.name}>
                <code>{column.name}</code> ({column.dtype})
              </li>
            ))}
          </ul>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {dataset.columns.map((column) => (
                    <th key={column.name}>{column.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dataset.sample_rows.map((row, index) => (
                  <tr key={index}>
                    {dataset.columns.map((column) => (
                      <td key={column.name}>{String(row[column.name] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
