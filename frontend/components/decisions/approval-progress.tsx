"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, Loader2, X } from "lucide-react";

import { apiClient } from "@/lib/api-client";
import type { ApprovalOutcome, ExecutionStepName } from "@/lib/api-types";
import { cn } from "@/lib/utils";

const STEPS: ExecutionStepName[] = ["PreCheck", "Apply", "Wait15s", "PostCheck", "Done"];
const POLL_INTERVAL_MS = 2000; // phase-03 §5 risk mitigation: "2-second poll interval"

/**
 * Phase-03 §5 asks for a streaming checklist driven by
 * `GET /operations/execution/{arn}`. That endpoint doesn't exist in
 * `backend` yet, and `approval_service.py#approve` calls
 * `start_sync_execution` -- the call already blocks until SUCCEEDED/
 * ROLLED_BACK, so `outcome`/`failureReason` below are known synchronously
 * the moment `POST /decisions/{id}/approve` resolves. This component still
 * polls the documented endpoint when `executionArn` is present (so it picks
 * up real streaming for free once a future backend phase ships it), but
 * treats any 404/502 the same way `EvidenceViewer` treats a missing
 * evidence ref: falls back to rendering the terminal `outcome` it already
 * has, not a crash or an infinite spinner.
 */
export function ApprovalProgress({
  phase,
  executionArn,
  outcome,
  failureReason,
}: {
  phase: "submitting" | "done";
  executionArn: string | null;
  outcome: ApprovalOutcome | null;
  failureReason: string | null;
}) {
  const { data, isError } = useQuery({
    queryKey: ["execution-status", executionArn],
    queryFn: () => apiClient.getExecutionStatus(executionArn as string),
    enabled: phase === "submitting" && executionArn !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "RUNNING" ? POLL_INTERVAL_MS : false;
    },
    retry: false,
  });

  const failedStep = isError ? null : data?.failed_step ?? null;
  const terminalFromResponse = phase === "done";

  function stepState(step: ExecutionStepName): "done" | "failed" | "pending" | "skipped" {
    if (terminalFromResponse) {
      if (step === "Done") return outcome === "SUCCEEDED" ? "done" : "failed";
      if (outcome === "ROLLED_BACK" || outcome === "REJECTED") {
        return step === "PreCheck" || step === "Apply" ? "done" : "failed";
      }
      return "done";
    }
    if (failedStep === step) return "failed";
    const stepIndex = STEPS.indexOf(step);
    const currentIndex = data?.current_step ? STEPS.indexOf(data.current_step) : -1;
    if (currentIndex === -1) return "pending";
    return stepIndex < currentIndex ? "done" : stepIndex === currentIndex ? "pending" : "pending";
  }

  return (
    <ol aria-label="Approval progress" className="space-y-2">
      {STEPS.map((step) => {
        const stepStatus = stepState(step);
        return (
          <li key={step} className="flex items-center gap-2 text-sm">
            {stepStatus === "done" && <Check className="h-4 w-4 text-severity-low" aria-hidden />}
            {stepStatus === "failed" && <X className="h-4 w-4 text-destructive" aria-hidden />}
            {stepStatus === "pending" && phase === "submitting" && (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />
            )}
            {stepStatus === "pending" && phase === "done" && <span className="h-4 w-4" />}
            <span className={cn(stepStatus === "failed" && "text-destructive")}>{step}</span>
          </li>
        );
      })}
      {failureReason && <p className="text-sm text-destructive">{failureReason}</p>}
      {isError && phase === "submitting" && (
        <p className="text-xs text-muted-foreground">
          Live step-by-step progress isn&apos;t available yet -- showing the final result once it arrives.
        </p>
      )}
    </ol>
  );
}
