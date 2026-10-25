/**
 * Mirrors the backend's AgentEvent payload shapes (src/sandbox_analyst/agent/events.py,
 * agent/loop.py's `_*_payload` builders) and the API's response shapes (docs/api.md).
 */

export type EventType =
  | "run_started"
  | "profile"
  | "llm_request"
  | "llm_response"
  | "code"
  | "static_check"
  | "exec_started"
  | "exec_result"
  | "answer"
  | "evidence"
  | "observation"
  | "run_finished";

export interface AgentEvent {
  run_id: string;
  seq: number;
  ts: number;
  type: EventType;
  attempt: number;
  payload: Record<string, unknown>;
}

export interface Violation {
  rule_id: string;
  line: number;
  col: number;
  message: string;
}

export interface RunStartedPayload {
  prompt_version: string;
  file_name: string;
  question: string;
  constraints: string | null;
  answer_format: string | null;
}

export interface ProfilePayload {
  file_name: string;
  n_rows: number;
  n_cols: number;
}

export interface ChatMessage {
  role: string;
  content: string;
}

export interface LlmRequestPayload {
  messages: ChatMessage[];
}

export interface LlmResponsePayload {
  text: string;
  reasoning: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  finish_reason: string | null;
}

export interface CodePayload {
  code: string | null;
}

export interface StaticCheckPayload {
  ok: boolean;
  violations: Violation[];
}

export interface ExecStartedPayload {
  timeout_s: number;
}

export interface ExecError {
  name: string;
  value: string;
  traceback: string;
}

/**
 * The normal shape, or a `crashed`/`unavailable` shape on a sandbox-infra
 * failure -- in which case `error` is a plain message string, not an
 * `ExecError` object (see agent/loop.py's `exec_result` emit calls).
 */
export interface ExecResultPayload {
  stdout?: string;
  stderr?: string;
  exit_code?: number | null;
  error?: ExecError | string | null;
  images?: string[];
  duration_ms?: number;
  timed_out?: boolean;
  truncated?: boolean;
  crashed?: boolean;
  unavailable?: boolean;
}

export interface AnswerItem {
  name: string;
  value: string;
}

export interface AnswerPayload {
  answers: AnswerItem[];
  explanation: string;
}

export interface EvidenceItem {
  name: string;
  value: string;
  passed: boolean;
  reason: string;
}

export interface EvidencePayload {
  results: EvidenceItem[];
}

export interface ObservationPayload {
  text: string;
}

export interface RunFinishedPayload {
  status: string;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_latency_ms: number;
  sandbox_usd: number;
}

// --- REST response shapes (docs/api.md) ---

export interface ColumnInfo {
  name: string;
  dtype: string;
}

export interface DatasetSummary {
  dataset_id: string;
  file_name: string;
  n_rows: number;
  n_cols: number;
  columns: ColumnInfo[];
  sample_rows: Record<string, unknown>[];
}

export interface ExampleInfo {
  title: string;
  description: string;
  file_name: string;
  questions: string[];
}

export type ExamplesResponse = Record<string, ExampleInfo>;

export interface HealthResponse {
  status: string;
  version: string;
  provider: string;
  model: string;
  sandbox: string;
}

export interface RunCreateResponse {
  run_id: string;
}

export interface AttemptSummary {
  attempt: number;
  has_code: boolean;
  check_ok: boolean | null;
  n_check_violations: number;
  exec_ok: boolean | null;
  timed_out: boolean | null;
  answered: boolean;
  observation: string | null;
}

export interface RunSummary {
  run_id: string;
  dataset_id: string;
  question: string;
  status: string;
  answers: AnswerItem[];
  explanation: string;
  code: string;
  stdout_tail: string;
  evidence: EvidenceItem[];
  attempts: AttemptSummary[];
  chart_urls: string[];
  prompt_tokens: number;
  completion_tokens: number;
  /** Total wall time, run_started -> run_finished (the headline "Time" stat). */
  wall_time_ms: number;
  /** Sum of LLM call latencies -- a secondary stat, not the headline time. */
  llm_time_ms: number;
  /** Sum of sandbox exec durations -- a secondary stat. */
  sandbox_time_ms: number;
  /** The exception TYPE only (e.g. "FileNotFoundError") on an unexpected failure; never its message. */
  error: string | null;
}

export interface ApiErrorBody {
  error: string;
  detail: string;
}
