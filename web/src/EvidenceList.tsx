import type { EvidenceItem } from "./types";

export function EvidenceList({ items }: { items: EvidenceItem[] }): JSX.Element | null {
  if (items.length === 0) {
    return null;
  }
  return (
    <ul className="evidence-list">
      {items.map((item) => (
        <li
          key={item.name}
          className={`evidence-item ${item.passed ? "evidence-pass" : "evidence-fail"}`}
        >
          <span className="evidence-badge">{item.passed ? "Verified" : "Not found"}</span>
          <span className="evidence-name">{item.name}</span>
          <span className="evidence-value">{item.value}</span>
        </li>
      ))}
    </ul>
  );
}
