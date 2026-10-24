import { useEffect, useRef, useState } from "react";

import { runEventsUrl } from "./api";
import type { AgentEvent } from "./types";

/**
 * Subscribes to a run's SSE stream and returns the deduped, seq-ordered
 * event list seen so far. On reconnect the server replays every event
 * already recorded (docs/api.md), so a seq-keyed map is what makes that
 * replay idempotent instead of duplicating events in the UI.
 */
export function useRunEvents(runId: string | null): AgentEvent[] {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const seenRef = useRef<Map<number, AgentEvent>>(new Map());

  useEffect(() => {
    seenRef.current = new Map();
    setEvents([]);
    if (runId === null) {
      return undefined;
    }

    const source = new EventSource(runEventsUrl(runId));

    source.onmessage = (message) => {
      let event: AgentEvent;
      try {
        event = JSON.parse(message.data) as AgentEvent;
      } catch {
        return;
      }
      if (seenRef.current.has(event.seq)) {
        return;
      }
      seenRef.current.set(event.seq, event);
      setEvents(Array.from(seenRef.current.values()).sort((a, b) => a.seq - b.seq));
      if (event.type === "run_finished") {
        source.close();
      }
    };

    // EventSource reconnects on its own on a transient drop; the server
    // replays past events on that new connection and the dedupe above
    // makes re-receiving them safe. No manual retry loop is needed here.
    source.onerror = () => undefined;

    return () => {
      source.close();
    };
  }, [runId]);

  return events;
}
