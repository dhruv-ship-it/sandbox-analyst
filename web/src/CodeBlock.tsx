import { useState } from "react";

import { tokenizePython } from "./highlight";

interface CodeBlockProps {
  code: string;
  label?: string;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  showCopy?: boolean;
}

export function CodeBlock({
  code,
  label,
  collapsible = false,
  defaultCollapsed = false,
  showCopy = false,
}: CodeBlockProps): JSX.Element {
  const [collapsed, setCollapsed] = useState(collapsible && defaultCollapsed);
  const [copied, setCopied] = useState(false);
  const tokens = tokenizePython(code);

  async function handleCopy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="code-block">
      {(label !== undefined || showCopy || collapsible) && (
        <div className="code-block-header">
          {label !== undefined && <span className="code-block-label">{label}</span>}
          <div className="code-block-actions">
            {showCopy && (
              <button type="button" className="btn-link" onClick={() => void handleCopy()}>
                {copied ? "Copied" : "Copy"}
              </button>
            )}
            {collapsible && (
              <button
                type="button"
                className="btn-link"
                aria-expanded={!collapsed}
                onClick={() => setCollapsed((value) => !value)}
              >
                {collapsed ? "Show code" : "Hide code"}
              </button>
            )}
          </div>
        </div>
      )}
      {!collapsed && (
        <pre className="code-pre">
          <code>
            {tokens.map((token, index) => (
              <span key={index} className={token.className}>
                {token.text}
              </span>
            ))}
          </code>
        </pre>
      )}
    </div>
  );
}
