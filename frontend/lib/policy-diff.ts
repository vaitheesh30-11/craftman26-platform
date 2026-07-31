// Line-level LCS diff for the Approval Drawer's policy-diff step (phase-03
// §3 step 1). No `diff`/`jsondiffpatch` package is in `package.json` --
// rather than add a dependency for something the diff is only ever run on
// pretty-printed JSON up to ~6 KB (phase-03 §7 acceptance criterion), a
// small classic LCS-based line diff is cheap enough to write and test
// in-repo, and keeps the bundle free of a diff library no other phase needs.

export type DiffLineKind = "unchanged" | "added" | "removed";

export interface DiffLine {
  kind: DiffLineKind;
  value: string;
  // 1-based line numbers in the respective side; `null` when the line
  // doesn't exist on that side (added/removed).
  leftLine: number | null;
  rightLine: number | null;
}

function linesOf(document: unknown): string[] {
  return JSON.stringify(document, null, 2).split("\n");
}

/**
 * Longest-common-subsequence line diff, unified into a single ordered list
 * (each entry already knows which side(s) it belongs to) so both the
 * side-by-side and unified renderers can share one computation.
 */
export function diffPolicies(current: unknown, proposed: unknown): DiffLine[] {
  const left = linesOf(current);
  const right = linesOf(proposed);
  const n = left.length;
  const m = right.length;

  // dp[i][j] = length of LCS of left[i:] and right[j:]. Flat
  // `Int32Array((n+1)*(m+1))` rather than `number[][]` -- a nested-array
  // LCS table would need a `T | undefined` check (`tsconfig.json`'s
  // `noUncheckedIndexedAccess`) at every one of the four indexes per cell;
  // one `at()` helper below absorbs that single `?? 0` in one place
  // instead (still `T | undefined` for a typed array, just centralized).
  const width = m + 1;
  const dp = new Int32Array((n + 1) * width);
  const at = (i: number, j: number): number => dp[i * width + j] ?? 0;

  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      const same = (left[i] ?? "") === (right[j] ?? "");
      const value = same ? at(i + 1, j + 1) + 1 : Math.max(at(i + 1, j), at(i, j + 1));
      dp[i * width + j] = value;
    }
  }

  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    const leftValue: string = left[i] ?? "";
    const rightValue: string = right[j] ?? "";
    if (leftValue === rightValue) {
      result.push({ kind: "unchanged", value: leftValue, leftLine: i + 1, rightLine: j + 1 });
      i += 1;
      j += 1;
    } else if (at(i + 1, j) >= at(i, j + 1)) {
      result.push({ kind: "removed", value: leftValue, leftLine: i + 1, rightLine: null });
      i += 1;
    } else {
      result.push({ kind: "added", value: rightValue, leftLine: null, rightLine: j + 1 });
      j += 1;
    }
  }
  while (i < n) {
    result.push({ kind: "removed", value: left[i] ?? "", leftLine: i + 1, rightLine: null });
    i += 1;
  }
  while (j < m) {
    result.push({ kind: "added", value: right[j] ?? "", leftLine: null, rightLine: j + 1 });
    j += 1;
  }
  return result;
}

export function diffHasChanges(diff: DiffLine[]): boolean {
  return diff.some((line) => line.kind !== "unchanged");
}
