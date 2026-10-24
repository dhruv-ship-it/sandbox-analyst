/**
 * Typed calls against the public API (docs/api.md). Every non-2xx response
 * is turned into an `ApiRequestError` carrying a friendly, human-readable
 * message built from the API's own `{error, detail}` JSON body.
 */

import type {
  ApiErrorBody,
  DatasetSummary,
  ExamplesResponse,
  HealthResponse,
  RunCreateResponse,
  RunSummary,
} from "./types";

const ERROR_TEMPLATES: Record<string, (detail: string) => string> = {
  invalid_dataset: (detail) => `That file couldn't be used: ${detail}`,
  request_too_large: (detail) => `That file is too large: ${detail}`,
  rate_limited: (detail) => detail,
  validation_error: (detail) => detail,
  not_found: (detail) => detail,
  http_error: (detail) => detail,
  internal_error: () => "Something went wrong on our end. Please try again.",
};

export function friendlyMessage(status: number, body: ApiErrorBody): string {
  const template = ERROR_TEMPLATES[body.error];
  if (template) {
    return template(body.detail);
  }
  return body.detail || `Request failed with status ${status}.`;
}

export class ApiRequestError extends Error {
  status: number;
  code: string;
  detail: string;

  constructor(status: number, body: ApiErrorBody) {
    super(friendlyMessage(status, body));
    this.name = "ApiRequestError";
    this.status = status;
    this.code = body.error;
    this.detail = body.detail;
  }
}

async function parseErrorBody(response: Response): Promise<ApiErrorBody> {
  try {
    const data = (await response.json()) as Partial<ApiErrorBody>;
    return {
      error: data.error ?? "unknown",
      detail: data.detail ?? `request failed with status ${response.status}`,
    };
  } catch {
    return { error: "unknown", detail: `request failed with status ${response.status}` };
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new ApiRequestError(response.status, await parseErrorBody(response));
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health");
}

export function listExamples(): Promise<ExamplesResponse> {
  return request<ExamplesResponse>("/api/examples");
}

export function loadExample(name: string): Promise<DatasetSummary> {
  return request<DatasetSummary>(`/api/examples/${encodeURIComponent(name)}/load`, {
    method: "POST",
  });
}

export function uploadDataset(file: File): Promise<DatasetSummary> {
  const body = new FormData();
  body.append("file", file);
  return request<DatasetSummary>("/api/datasets", { method: "POST", body });
}

export function createRun(datasetId: string, question: string): Promise<RunCreateResponse> {
  return request<RunCreateResponse>("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, question }),
  });
}

export function getRun(runId: string): Promise<RunSummary> {
  return request<RunSummary>(`/api/runs/${encodeURIComponent(runId)}`);
}

export function runEventsUrl(runId: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/events`;
}

export function artifactUrl(runId: string, name: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(name)}`;
}

export function traceUrl(runId: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/trace`;
}
