import type { FeatureId } from "@/lib/api-types";

// Mirrors `app/(dashboard)/page.tsx`'s `FEATURES` labels field-for-field.
// Not imported from there (that file isn't a shared module) to avoid
// coupling the dashboard tile layout to the findings inbox's filter UI.
export const FEATURE_LABELS: Record<FeatureId, string> = {
  F1: "PassRole Blast Radius",
  F2: "Org-Context Policy Validator",
  F3: "S3 Data Event Enricher",
  F4: "SCP Change Impact Analyzer",
  F5: "SSO Emergency Session Killer",
  F6: "Management Account Shadow Guard",
  F7: "SCP Collision Resolver",
  F8: "SLR Breakage Pre-Scanner",
};

export const FEATURE_IDS = Object.keys(FEATURE_LABELS) as FeatureId[];
