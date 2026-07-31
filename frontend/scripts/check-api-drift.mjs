#!/usr/bin/env node
// phase-00 §7: "openapi-typescript regeneration checked in; PR fails on
// drift." Regenerates lib/api-types.gen.ts into a scratch file and diffs
// it byte-for-byte against the checked-in version rather than overwriting
// it in place, so a drifted PR fails loudly instead of silently updating.
import { execFileSync } from "node:child_process";
import { readFileSync, unlinkSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");
const checkedIn = path.join(frontendRoot, "lib", "api-types.gen.ts");
const scratch = path.join(frontendRoot, "lib", "api-types.gen.drift-check.ts");
const golden = path.join(frontendRoot, "..", "backend", "openapi.golden.json");

execFileSync(
  "node",
  [
    path.join(frontendRoot, "node_modules", ".bin", "openapi-typescript"),
    golden,
    "-o",
    scratch,
  ],
  { stdio: "inherit" },
);

try {
  const expected = readFileSync(checkedIn, "utf8");
  const actual = readFileSync(scratch, "utf8");
  if (expected !== actual) {
    console.error(
      "lib/api-types.gen.ts is out of date with backend/openapi.golden.json.\n" +
        "Run `pnpm generate:api-types` and commit the result.",
    );
    process.exit(1);
  }
  console.log("lib/api-types.gen.ts matches backend/openapi.golden.json.");
} finally {
  unlinkSync(scratch);
}
