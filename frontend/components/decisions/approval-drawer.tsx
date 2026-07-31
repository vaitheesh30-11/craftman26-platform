"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient, ApiError } from "@/lib/api-client";
import type { ApprovalOutcome, FindingOut } from "@/lib/api-types";
import type { CallerPersona } from "@/lib/principal";
import {
  isBackendApprovable,
  isSessionKill,
  remediationAction,
  remediationCurrentPolicy,
  remediationProposedPolicy,
  remediationTargetArn,
  remediationZelkovaCheck,
  shortTarget,
  type RemediationRecord,
} from "@/lib/remediation-format";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/use-toast";
import { PolicyDiff } from "@/components/decisions/policy-diff";
import { ZelkovaWitness } from "@/components/decisions/zelkova-witness";
import { ImpactSummary } from "@/components/decisions/impact-summary";
import { ConfirmationBox, isConfirmationValid, type ConfirmationValue } from "@/components/decisions/confirmation-box";
import { ApprovalProgress } from "@/components/decisions/approval-progress";

type StepId = "diff" | "zelkova" | "impact" | "confirm" | "apply";
const STEPS: { id: StepId; label: string }[] = [
  { id: "diff", label: "1. Diff" },
  { id: "zelkova", label: "2. Zelkova" },
  { id: "impact", label: "3. Impact" },
  { id: "confirm", label: "4. Confirmation" },
  { id: "apply", label: "5. Apply" },
];

interface DrawerResult {
  outcome: ApprovalOutcome;
  remediationApplied: Record<string, unknown>;
  executionArn: string | null;
  failureReason: string | null;
}

export function ApprovalDrawer({
  open,
  onOpenChange,
  decisionId,
  remediationIndex,
  remediation,
  finding,
  persona,
  onOutcome,
  onApplying,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  decisionId: string;
  remediationIndex: number;
  remediation: RemediationRecord;
  finding: FindingOut | null;
  persona: CallerPersona | null;
  onOutcome: (outcome: ApprovalOutcome) => void;
  onApplying: () => void;
}) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [stepIndex, setStepIndex] = useState(0);
  const [mode, setMode] = useState<"approve" | "reject">("approve");
  const [confirmation, setConfirmation] = useState<ConfirmationValue>({
    typedTarget: "",
    reviewed: false,
    reason: "",
  });
  const [rejectReason, setRejectReason] = useState("");
  const [result, setResult] = useState<DrawerResult | null>(null);

  const action = remediationAction(remediation);
  const targetArn = remediationTargetArn(remediation);
  const expectedTarget = shortTarget(targetArn);
  const sessionKill = isSessionKill(remediation);
  const isScpUpdate = action === "update_scp";

  const operatorGateFailed = isScpUpdate && !(persona?.isOperator ?? false);
  const breakGlassGateFailed = sessionKill && !(persona?.isBreakGlass ?? false);
  const confirmationValid = isConfirmationValid(expectedTarget, confirmation);
  const approveDisabled =
    !confirmationValid || operatorGateFailed || breakGlassGateFailed || !isBackendApprovable(remediation);

  const mutation = useMutation({
    mutationFn: async () => {
      if (mode === "reject") {
        return apiClient.rejectDecision(decisionId, { remediation_index: remediationIndex, reason: rejectReason, dry_run: false });
      }
      return apiClient.approveDecision(decisionId, {
        remediation_index: remediationIndex,
        reason: confirmation.reason,
        dry_run: false,
      });
    },
    onMutate: () => {
      setStepIndex(STEPS.length - 1);
      onApplying();
    },
    onSuccess: (response) => {
      setResult({
        outcome: response.state,
        remediationApplied: response.remediation_applied,
        executionArn: response.state_machine_execution_arn,
        failureReason: response.state === "ROLLED_BACK" ? "Post-check failed -- remediation was rolled back." : null,
      });
      onOutcome(response.state);
      void queryClient.invalidateQueries({ queryKey: ["decision", decisionId] });
      toast({
        title: response.state === "SUCCEEDED" ? "Remediation applied" : response.state === "REJECTED" ? "Remediation rejected" : "Remediation rolled back",
        description:
          response.state === "SUCCEEDED"
            ? "The state machine reported success. Evidence has been recorded."
            : response.state === "REJECTED"
              ? "This remediation was rejected and will not be applied."
              : "The post-check failed and the change was rolled back. See the runbook.",
        variant: response.state === "ROLLED_BACK" ? "destructive" : "default",
      });
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "The approval request failed unexpectedly.";
      setResult({ outcome: "ROLLED_BACK", remediationApplied: {}, executionArn: null, failureReason: message });
      toast({ title: "Approval failed", description: message, variant: "destructive" });
    },
  });

  function close() {
    onOpenChange(false);
    setStepIndex(0);
    setMode("approve");
    setConfirmation({ typedTarget: "", reviewed: false, reason: "" });
    setRejectReason("");
    setResult(null);
  }

  const step = STEPS[stepIndex]?.id ?? "diff";

  return (
    <Sheet open={open} onOpenChange={(next) => (next ? onOpenChange(next) : close())}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="font-mono">{action}</SheetTitle>
          <SheetDescription>Target: {targetArn ?? "unknown"}</SheetDescription>
        </SheetHeader>

        <nav aria-label="Approval steps" className="mt-4 flex flex-wrap gap-1.5">
          {STEPS.map((s, index) => (
            <Badge key={s.id} variant={index === stepIndex ? "default" : "outline"}>
              {s.label}
            </Badge>
          ))}
        </nav>

        <div className="mt-4 space-y-4">
          {step === "diff" && (
            <PolicyDiff current={remediationCurrentPolicy(remediation)} proposed={remediationProposedPolicy(remediation)} />
          )}

          {step === "zelkova" && <ZelkovaWitness zelkovaCheck={remediationZelkovaCheck(remediation)} />}

          {step === "impact" && <ImpactSummary finding={finding} />}

          {step === "confirm" && (
            <div className="space-y-4">
              <div className="flex gap-2">
                <Button type="button" size="sm" variant={mode === "approve" ? "default" : "outline"} onClick={() => setMode("approve")}>
                  Approve
                </Button>
                <Button type="button" size="sm" variant={mode === "reject" ? "default" : "outline"} onClick={() => setMode("reject")}>
                  Reject
                </Button>
              </div>

              {mode === "approve" ? (
                <>
                  <ConfirmationBox expectedTarget={expectedTarget} value={confirmation} onChange={setConfirmation} />
                  {operatorGateFailed && (
                    <p className="text-sm text-destructive" role="alert">
                      Operator role required. SCP updates can only be approved by a member of SentinelOperators.
                    </p>
                  )}
                  {breakGlassGateFailed && (
                    <p className="text-sm text-destructive" role="alert">
                      Break-glass session required. This remediation terminates a live session and needs the
                      two-signer BreakGlass tag.
                    </p>
                  )}
                  {!isBackendApprovable(remediation) && (
                    <p className="text-sm text-muted-foreground">
                      {`"${action}" is not an approvable remediation action -- backend will reject this request.`}
                    </p>
                  )}
                </>
              ) : (
                <div>
                  <label htmlFor="reject-reason" className="text-xs font-semibold uppercase text-muted-foreground">
                    Reason
                  </label>
                  <textarea
                    id="reject-reason"
                    className="mt-1.5 w-full rounded-md border border-input bg-background p-2 text-sm"
                    rows={3}
                    value={rejectReason}
                    onChange={(e) => setRejectReason(e.target.value)}
                  />
                </div>
              )}
            </div>
          )}

          {step === "apply" && (
            <div className="space-y-3">
              <ApprovalProgress
                phase={result ? "done" : "submitting"}
                executionArn={result?.executionArn ?? null}
                outcome={result?.outcome ?? null}
                failureReason={result?.failureReason ?? null}
              />
              {result?.outcome === "SUCCEEDED" && (
                <div className="rounded-md border border-severity-low/40 bg-severity-low/10 p-3 text-sm">
                  Applied successfully.{" "}
                  {decisionId && <span className="font-mono text-xs">decision {decisionId}</span>}
                </div>
              )}
              {result?.outcome === "ROLLED_BACK" && (
                <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
                  Rolled back. See the runbook for `{action}` remediations before retrying.
                </div>
              )}
              {result?.outcome === "REJECTED" && (
                <div className="rounded-md border p-3 text-sm">This remediation was rejected.</div>
              )}
            </div>
          )}
        </div>

        <SheetFooter className="mt-6">
          {step !== "apply" && stepIndex > 0 && (
            <Button type="button" variant="outline" onClick={() => setStepIndex((i) => i - 1)}>
              Back
            </Button>
          )}
          {step !== "confirm" && step !== "apply" && (
            <Button type="button" onClick={() => setStepIndex((i) => i + 1)}>
              Next
            </Button>
          )}
          {step === "confirm" && mode === "approve" && (
            <Button type="button" disabled={approveDisabled || mutation.isPending} onClick={() => mutation.mutate()}>
              Approve &amp; apply
            </Button>
          )}
          {step === "confirm" && mode === "reject" && (
            <Button type="button" variant="destructive" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
              Reject
            </Button>
          )}
          {step === "apply" && (
            <Button type="button" onClick={close}>
              Close
            </Button>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
