import { diffLines } from "diff";

interface DiffRow {
  key: string;
  kind: "added" | "removed" | "context";
  text: string;
}

function toRows(previousCode: string, nextCode: string): DiffRow[] {
  const changes = diffLines(previousCode, nextCode);
  const rows: DiffRow[] = [];
  let index = 0;
  for (const change of changes) {
    const kind: DiffRow["kind"] = change.added === true ? "added" : change.removed === true ? "removed" : "context";
    const lines = change.value.split("\n");
    const usable = lines[lines.length - 1] === "" ? lines.slice(0, -1) : lines;
    for (const text of usable) {
      rows.push({ key: `${index}`, kind, text });
      index += 1;
    }
  }
  return rows;
}

/** A plain-text line diff: every row is rendered as a React text child, never HTML. */
export function DiffView({
  previousCode,
  nextCode,
}: {
  previousCode: string;
  nextCode: string;
}): JSX.Element {
  const rows = toRows(previousCode, nextCode);
  return (
    <pre className="diff-view">
      {rows.map((row) => (
        <div key={row.key} className={`diff-line diff-line-${row.kind}`}>
          <span className="diff-marker">
            {row.kind === "added" ? "+" : row.kind === "removed" ? "-" : " "}
          </span>
          <span className="diff-text">{row.text}</span>
        </div>
      ))}
    </pre>
  );
}
