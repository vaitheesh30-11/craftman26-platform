import type { DecisionOut } from "@/lib/api-types";
import type { TranscriptEntry, TurnEntry } from "@/store/chat-session";
import { ProgressLine } from "@/components/chat/progress-line";
import { ResultBlock } from "@/components/chat/result-block";

function TurnBlock({ entry }: { entry: TurnEntry }) {
  if (entry.state === "streaming") {
    return (
      <div className="max-w-[85%] space-y-1 rounded-lg bg-muted px-4 py-3" aria-live="polite">
        {entry.progressLines.length === 0 ? (
          <ProgressLine text="Sentinel Prime is thinking" />
        ) : (
          entry.progressLines.map((line, i) => <ProgressLine key={i} text={line} />)
        )}
      </div>
    );
  }
  if (entry.state === "done" && entry.result) {
    return <ResultBlock decision={entry.result as unknown as DecisionOut} />;
  }
  if (entry.state === "canceled") {
    return <p className="text-sm italic text-muted-foreground">Canceled.</p>;
  }
  return (
    <p className="text-sm text-destructive" role="alert">
      {entry.error?.message ?? "Something went wrong."}
      {entry.error?.correlation_id ? ` (correlation ${entry.error.correlation_id})` : ""}
    </p>
  );
}

export function MessageList({ transcript }: { transcript: TranscriptEntry[] }) {
  if (transcript.length === 0) {
    return <p className="text-sm text-muted-foreground">Ask Sentinel Prime about an IAM or SCP gap to begin.</p>;
  }

  return (
    <ol className="flex flex-col gap-4">
      {transcript.map((entry) =>
        entry.kind === "user" ? (
          <li key={entry.id} className="flex justify-end">
            <p className="max-w-[85%] rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground">{entry.text}</p>
          </li>
        ) : (
          <li key={entry.id} className="flex justify-start">
            <TurnBlock entry={entry} />
          </li>
        ),
      )}
    </ol>
  );
}
