"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { ChatQuery } from "@/lib/websocket-client";

const MAX_CHARS = 4_096;

const SUGGESTED_PROMPTS = [
  "Which roles can PassRole into an admin-equivalent role?",
  "Does any SCP have no effect on the management account?",
  "Will this SCP break a service-linked role?",
  "Show S3 buckets missing data-event coverage.",
];

interface PromptComposerProps {
  disabled: boolean;
  onSubmit: (query: ChatQuery) => void;
}

export function PromptComposer({ disabled, onSubmit }: PromptComposerProps) {
  const [text, setText] = useState("");
  const [includeArns, setIncludeArns] = useState(false);
  const [consentDataEvents, setConsentDataEvents] = useState(false);
  const [confirmKill, setConfirmKill] = useState(false);

  const submit = () => {
    const query_text = text.trim();
    if (!query_text || disabled) return;
    const hints: Record<string, string> = {};
    if (consentDataEvents) hints.consent_enable_data_events = "true";
    if (confirmKill) hints.confirm_kill = "true";
    onSubmit({ query_text, hints, include_arns_in_output: includeArns });
    setText("");
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {SUGGESTED_PROMPTS.map((prompt) => (
          <Button key={prompt} type="button" variant="outline" size="sm" onClick={() => setText(prompt)}>
            {prompt}
          </Button>
        ))}
      </div>

      <textarea
        aria-label="Message Sentinel Prime"
        value={text}
        maxLength={MAX_CHARS}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        rows={3}
        className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        placeholder="Ask Sentinel Prime..."
      />
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={includeArns} onChange={(e) => setIncludeArns(e.target.checked)} />
            Include ARNs in output
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={consentDataEvents}
              onChange={(e) => setConsentDataEvents(e.target.checked)}
            />
            Consent to enable CloudTrail data events (F3)
          </label>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={confirmKill} onChange={(e) => setConfirmKill(e.target.checked)} />
            Confirm session kill (F5)
          </label>
        </div>
        <span>
          {text.length}/{MAX_CHARS}
        </span>
      </div>
      <Button type="button" onClick={submit} disabled={disabled || !text.trim()}>
        Send
      </Button>
    </div>
  );
}
