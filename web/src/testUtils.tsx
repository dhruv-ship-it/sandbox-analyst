import type { ReactElement } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

/**
 * A minimal render helper so component tests don't need an extra testing
 * library dependency (see DECISIONS.md: the dependency budget for web/ is
 * react, react-dom, vite, typescript, vitest + two small libraries).
 */
export function renderToContainer(element: ReactElement): {
  container: HTMLDivElement;
  root: Root;
  unmount: () => void;
} {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(element);
  });
  return {
    container,
    root,
    unmount: () => {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
  };
}
