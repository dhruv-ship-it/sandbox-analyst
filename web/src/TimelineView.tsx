import { AttemptCard } from "./AttemptCard";
import type { AttemptState } from "./timeline";

export function Timeline({ attempts }: { attempts: AttemptState[] }): JSX.Element | null {
  if (attempts.length === 0) {
    return null;
  }
  return (
    <ol className="timeline">
      {attempts.map((attempt, index) => (
        <AttemptCard
          key={attempt.attempt}
          attempt={attempt}
          previousCode={index > 0 ? attempts[index - 1].code : null}
        />
      ))}
    </ol>
  );
}
