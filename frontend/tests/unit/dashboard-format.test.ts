import { describe, expect, it } from "vitest";

import type { FaultRecordOut, FindingOut } from "@/lib/api-types";
import {
  breakerTone,
  countAtLeastMedium,
  faultsByClass,
  formatUsd,
  parseCostReportBody,
  severityWeightedSparkline,
  topPrincipals,
  weeklyTrend,
} from "@/lib/dashboard-format";

function finding(overrides: Partial<FindingOut>): FindingOut {
  return {
    finding_id: "01JBQXFIXTURE",
    feature_id: "F1",
    account_id: "111122223333",
    principal_arn: "arn:aws:iam::111122223333:role/example-role",
    resource_arn: null,
    severity: "MEDIUM",
    title: "fixture",
    detail: "fixture",
    aws_doc_citation: {
      gap_id: "F1",
      quote: "q",
      source: "s",
      url: "https://docs.aws.amazon.com/x",
      retrieved_on: "2026-07-01",
    },
    payload: {},
    detected_at: new Date().toISOString(),
    expires_at: null,
    evidence_ref: null,
    status: "OPEN",
    ...overrides,
  };
}

describe("countAtLeastMedium", () => {
  it("counts only MEDIUM/HIGH/CRITICAL findings", () => {
    const findings = [
      finding({ severity: "INFO" }),
      finding({ severity: "LOW" }),
      finding({ severity: "MEDIUM" }),
      finding({ severity: "HIGH" }),
      finding({ severity: "CRITICAL" }),
    ];
    expect(countAtLeastMedium(findings)).toBe(3);
  });
});

describe("severityWeightedSparkline", () => {
  it("buckets findings into UTC day buckets weighted by severity rank", () => {
    const today = new Date().toISOString();
    const points = severityWeightedSparkline([finding({ severity: "CRITICAL", detected_at: today })], 3);
    expect(points).toHaveLength(3);
    expect(points.at(-1)?.value).toBe(4); // CRITICAL rank
    expect(points[0]?.value).toBe(0);
  });
});

describe("topPrincipals", () => {
  it("ranks by count descending and excludes findings with no principal_arn", () => {
    const findings = [
      finding({ principal_arn: "arn:a" }),
      finding({ principal_arn: "arn:a" }),
      finding({ principal_arn: "arn:b" }),
      finding({ principal_arn: null }),
    ];
    const result = topPrincipals(findings, 5);
    expect(result).toEqual([
      { principal: "arn:a", count: 2 },
      { principal: "arn:b", count: 1 },
    ]);
  });

  it("caps at the requested limit", () => {
    const findings = Array.from({ length: 10 }, (_, i) => finding({ principal_arn: `arn:${i}` }));
    expect(topPrincipals(findings, 5)).toHaveLength(5);
  });
});

describe("faultsByClass", () => {
  it("aggregates counts per fault_class", () => {
    const faults: FaultRecordOut[] = [
      {
        correlation_id: "c1",
        fault_class: "transient_throttling",
        origin: "o",
        action_taken: "retried",
        detail: "d",
        detected_at: new Date().toISOString(),
        resolved_at: null,
      },
      {
        correlation_id: "c2",
        fault_class: "transient_throttling",
        origin: "o",
        action_taken: "retried",
        detail: "d",
        detected_at: new Date().toISOString(),
        resolved_at: null,
      },
      {
        correlation_id: "c3",
        fault_class: "adapter_fault",
        origin: "o",
        action_taken: "escalated",
        detail: "d",
        detected_at: new Date().toISOString(),
        resolved_at: null,
      },
    ];
    expect(faultsByClass(faults)).toEqual({ transient_throttling: 2, adapter_fault: 1 });
  });
});

describe("breakerTone", () => {
  it("maps closed/half_open/open to good/warning/critical", () => {
    expect(breakerTone("closed")).toBe("good");
    expect(breakerTone("half_open")).toBe("warning");
    expect(breakerTone("open")).toBe("critical");
  });
});

describe("formatUsd", () => {
  it("formats as USD currency", () => {
    expect(formatUsd(1234.5)).toBe("$1,234.50");
  });
});

describe("weeklyTrend", () => {
  it("returns flat with null delta when there's no previous figure", () => {
    expect(weeklyTrend(100, null)).toEqual({ direction: "flat", deltaPct: null });
  });

  it("detects up/down beyond a 1% deadband", () => {
    expect(weeklyTrend(110, 100).direction).toBe("up");
    expect(weeklyTrend(90, 100).direction).toBe("down");
    expect(weeklyTrend(100.5, 100).direction).toBe("flat");
  });
});

describe("parseCostReportBody", () => {
  it("reads by_service figures and sums a total when none is given", () => {
    const parsed = parseCostReportBody({ by_service: { bedrock: 10, athena: 2, lambda: 1 } });
    expect(parsed).toEqual({ bedrockUsd: 10, athenaUsd: 2, lambdaUsd: 1, totalUsd: 13, previousWeekTotalUsd: null });
  });

  it("defaults every figure to 0 for an unrecognized shape instead of throwing", () => {
    expect(parseCostReportBody({ unexpected: "shape" })).toEqual({
      bedrockUsd: 0,
      athenaUsd: 0,
      lambdaUsd: 0,
      totalUsd: 0,
      previousWeekTotalUsd: null,
    });
  });
});
