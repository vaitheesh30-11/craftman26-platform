"use client";

import { useState } from "react";

import type { FindingOut, Severity } from "@/lib/api-types";
import {
  isSessionKill,
  remediationAction,
  remediationTargetArn,
  remediationTtlSeconds,
  type RemediationLifecycleState,
  type RemediationRecord,
} from "@/lib/remediation-format";
import { shortArn } from "@/lib/findings-format";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SeverityBadge } from "@/components/findings/severity-badge";
import { ApprovalDrawer } from "@/components/decisions/approval-drawer";
import type { CallerPersona } from "@/lib/principal";

const STATE_LABEL: Record<RemediationLifecycleState, string> = {
  proposed: "Proposed",
  approved: "Approved",
  rejected: "Rejected",
  applying: "Applying",
  applied: "Applied",
  "rolled-back": "Rolled back",
};

const STATE_VARIANT: Record<RemediationLifecycleState, BadgeProps["variant"]> = {
  proposed: "outline",
  approved: "default",
  rejected: "destructive",
  applying: "default",
  applied: "low",
  "rolled-back": "high",
};

function ttlLabel(ttlSeconds: number | null): string | null {
  if (ttlSeconds === null) return null;
  if (ttlSeconds < 3600) return `TTL ${Math.round(ttlSeconds / 60)}m`;
  if (ttlSeconds < 86400) return `TTL ${Math.round(ttlSeconds / 3600)}h`;
  return `TTL ${Math.round(ttlSeconds / 86400)}d`;
}

export function RemediationCard({
  decisionId,
  remediationIndex,
  remediation,
  finding,
  severity,
  persona,
}: {
  decisionId: string;
  remediationIndex: number;
  remediation: RemediationRecord;
  finding: FindingOut | null;
  severity: Severity | null;
  persona: CallerPersona | null;
}) {
  const [state, setState] = useState<RemediationLifecycleState>("proposed");
  const [open, setOpen] = useState(false);

  const action = remediationAction(remediation);
  const targetArn = remediationTargetArn(remediation);
  const ttl = ttlLabel(remediationTtlSeconds(remediation));
  const sessionKill = isSessionKill(remediation);

  return (
    <Card data-state={state}>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base font-mono">{action}</CardTitle>
          {severity && <SeverityBadge severity={severity} />}
          <Badge variant={STATE_VARIANT[state]}>{STATE_LABEL[state]}</Badge>
          {sessionKill && <Badge variant="destructive">Break-glass session required</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-sm text-muted-foreground">
          Target: <span className="font-mono text-foreground">{shortArn(targetArn)}</span>
          {ttl && <span className="ml-2">· {ttl}</span>}
        </p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={state === "approved" || state === "applied" || state === "rejected" || state === "applying"}
          onClick={() => setOpen(true)}
        >
          Review
        </Button>
      </CardContent>

      <ApprovalDrawer
        open={open}
        onOpenChange={setOpen}
        decisionId={decisionId}
        remediationIndex={remediationIndex}
        remediation={remediation}
        finding={finding}
        persona={persona}
        onOutcome={(outcome) => {
          if (outcome === "SUCCEEDED") setState("applied");
          else if (outcome === "ROLLED_BACK") setState("rolled-back");
          else setState("rejected");
        }}
        onApplying={() => setState("applying")}
      />
    </Card>
  );
}
