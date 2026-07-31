import type { Severity } from "@/lib/api-types";
import { Badge, type BadgeProps } from "@/components/ui/badge";

// Same severity->variant mapping as `components/chat/finding-chip.tsx`,
// pulled out here so both the chat surface and the findings inbox render
// severity identically without duplicating the `Record`.
const SEVERITY_VARIANT: Record<Severity, BadgeProps["variant"]> = {
  INFO: "info",
  LOW: "low",
  MEDIUM: "medium",
  HIGH: "high",
  CRITICAL: "critical",
};

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  return (
    <Badge variant={SEVERITY_VARIANT[severity]} className={className}>
      {severity}
    </Badge>
  );
}
