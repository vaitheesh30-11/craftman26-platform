"use client";

import { z } from "zod";

import { Input } from "@/components/ui/input";

/**
 * Phase-03 §3 step 4: typed target confirmation + reviewed checkbox +
 * optional reason (>=20 chars when non-empty). §8 risk: this friction is
 * intentional -- "typed-confirmation step is intentionally friction."
 * Exported so `ApprovalDrawer`'s gate check and this file's own test both
 * validate against one schema.
 */
export function confirmationSchema(expectedTarget: string) {
  return z.object({
    typedTarget: z.string().refine((v) => v === expectedTarget, {
      message: `Must match "${expectedTarget}" exactly.`,
    }),
    reviewed: z.literal(true, {
      message: "You must confirm you reviewed the diff, Zelkova result, and impact.",
    }),
    reason: z.string().refine((v) => v.length === 0 || v.length >= 20, {
      message: "Reason must be empty or at least 20 characters.",
    }),
  });
}

export interface ConfirmationValue {
  typedTarget: string;
  reviewed: boolean;
  reason: string;
}

export function isConfirmationValid(expectedTarget: string, value: ConfirmationValue): boolean {
  return confirmationSchema(expectedTarget).safeParse(value).success;
}

export function ConfirmationBox({
  expectedTarget,
  value,
  onChange,
}: {
  expectedTarget: string;
  value: ConfirmationValue;
  onChange: (value: ConfirmationValue) => void;
}) {
  const result = confirmationSchema(expectedTarget).safeParse(value);
  const fieldErrors = result.success ? {} : result.error.formErrors.fieldErrors;

  return (
    <div className="space-y-4" role="group" aria-label="Approval confirmation">
      <div>
        <label htmlFor="confirm-target" className="text-xs font-semibold uppercase text-muted-foreground">
          Type &ldquo;{expectedTarget}&rdquo; to confirm the target
        </label>
        <Input
          id="confirm-target"
          className="mt-1.5"
          value={value.typedTarget}
          onChange={(e) => onChange({ ...value, typedTarget: e.target.value })}
          aria-invalid={value.typedTarget.length > 0 && value.typedTarget !== expectedTarget}
          autoComplete="off"
        />
        {value.typedTarget.length > 0 && value.typedTarget !== expectedTarget && (
          <p className="mt-1 text-xs text-destructive">{fieldErrors.typedTarget?.[0]}</p>
        )}
      </div>

      <div className="flex items-start gap-2">
        <input
          id="confirm-reviewed"
          type="checkbox"
          className="mt-0.5 h-4 w-4"
          checked={value.reviewed}
          onChange={(e) => onChange({ ...value, reviewed: e.target.checked })}
        />
        <label htmlFor="confirm-reviewed" className="text-sm">
          I have reviewed the diff, Zelkova result, and impact.
        </label>
      </div>

      <div>
        <label htmlFor="confirm-reason" className="text-xs font-semibold uppercase text-muted-foreground">
          Reason (optional, minimum 20 characters if provided)
        </label>
        <textarea
          id="confirm-reason"
          className="mt-1.5 w-full rounded-md border border-input bg-background p-2 text-sm"
          rows={3}
          value={value.reason}
          onChange={(e) => onChange({ ...value, reason: e.target.value })}
        />
        {value.reason.length > 0 && value.reason.length < 20 && (
          <p className="mt-1 text-xs text-destructive">{fieldErrors.reason?.[0]}</p>
        )}
      </div>
    </div>
  );
}
