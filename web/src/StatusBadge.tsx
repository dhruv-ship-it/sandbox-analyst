const STATUS_LABELS: Record<string, string> = {
  idle: "Idle",
  running: "Running",
  answered: "Answered",
  failed: "Not verified",
  repeated_failure: "Stopped: repeated failure",
  tool_failure: "Stopped: sandbox trouble",
  budget_exceeded: "Stopped: budget exceeded",
  llm_error: "Stopped: model unavailable",
  error: "Unexpected error",
};

export function StatusBadge({ status }: { status: string }): JSX.Element {
  const label = STATUS_LABELS[status] ?? status;
  return <span className={`status-badge status-${status}`}>{label}</span>;
}
