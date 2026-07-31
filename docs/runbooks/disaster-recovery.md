# IAM Sentinel — Disaster Recovery Runbook

Source: `agents/docs/phase-17-self-healing.txt` §9 (Region Failover) + §6-8
(watchdog/repair/drift). See `docs/decisions/0032` for what is real vs.
deferred as of this phase.

## 1. Topology

- Prime and every specialist are deployed in `us-east-1` (primary) and
  `us-west-2` (standby). **As of this phase, only `us-east-1` exists** —
  aws-infra has synthesized single-region stacks through phase-08; the
  standby region's stacks are not yet provisioned. This runbook documents
  the target topology so standing up the standby region is a deployment
  exercise, not a design exercise.
- Cross-region DDB global tables: `SentinelFindings`, `SentinelDecisions`,
  `SentinelMemoryEpisodic`, `SentinelPolicies`.
- S3 Cross-Region Replication on the evidence bucket
  (`sentinel-evidence-{stage}`).
- Bedrock KB: replicated ingest in the standby region, warm but not queried
  until failover (degrades gracefully — higher latency, not unavailable).

## 2. Failover trigger

Route 53 health check on Prime's API Gateway (`SentinelApi`, aws-infra
phase-07). On 3 consecutive failed health checks, DNS flips to the standby
region (30s TTL on the record).

## 3. Failover steps (manual until §9's automation is provisioned)

1. Confirm the primary region outage is real, not a health-check false
   positive: check `SentinelApi`'s CloudWatch 5xx/latency dashboards and
   the underlying Lambda's error rate directly.
2. If confirmed, verify Route 53 has already flipped (it should, within
   30s of the 3rd failed check); if not, manually update the failover
   record.
3. Verify the standby region's Prime/specialist Lambdas are warm (cold
   starts add latency to the first requests after failover).
4. Verify DDB global table replication lag for `SentinelFindings`/
   `SentinelDecisions`/`SentinelMemoryEpisodic`/`SentinelPolicies` is
   within acceptable bounds (`ReplicationGroupTypes` / `ReplicaStatus` via
   `dynamodb:DescribeTable`) — a large lag means recent writes in the
   primary region may not be visible yet in the standby.
5. Verify the standby region's KB ingest is current enough to answer
   citation-grounded queries (degraded latency is acceptable; missing data
   is not).
6. Monitor `SentinelStuckSession`/`SentinelFaults` in the standby region —
   the watchdog and fault-recording machinery (agents phase-17) run
   per-region and must be healthy in the standby before real traffic lands
   on it.
7. Once primary region recovers: verify no split-brain writes occurred
   during the failover window (check `SentinelDecisions`/`SentinelFindings`
   for near-duplicate correlation_ids written in both regions in the same
   window); fail back via the same Route 53 mechanism once confirmed clean.

## 4. RTO budget (§9 acceptance criterion: p95 total RTO ≤ 5 minutes)

| Phase                                  | Budget   |
|-----------------------------------------|----------|
| Health-check failure detection (3x)     | ≤ 90s    |
| DNS TTL propagation                     | ≤ 30s    |
| Standby Lambda cold start (first calls) | ≤ 60s    |
| Operator verification (steps 4-6 above) | ≤ 180s   |
| **Total**                               | **≤ 5min** |

Not independently measured against a real deployed standby region as of
this phase (§13); re-verify once `us-west-2` is actually provisioned.

## 5. Cost mitigation (§9 risk: cross-region failover cost overhead)

Standby region runs minimum ACUs / provisioned concurrency; Bedrock KB
standby is warm but not queried until failover. Total standby overhead is
budgeted at ≤ 20% of primary spend — track via the `SentinelBedrockDollars`
anomaly-detection alarm (aws-infra `EventStack._build_bedrock_spend_anomaly_alarm`)
scoped per-region once the standby region has its own Bedrock spend to
watch.

## 6. Watchdog / repair / drift during an incident

- The watchdog (agents phase-17 §6, `watchdog/scanner.py`) keeps running
  independently in whichever region is currently primary — a region
  failover does not pause self-healing, it just means the watchdog's
  `SentinelDecisionsInFlight` reads are now against the standby region's
  table replica.
- Repair Lambdas (§7) honor a maintenance-window SSM flag (§14 risk
  mitigation) — **set this flag before any manual incident-response change
  to a Sentinel stack**, so `drift/detector.py` does not fight an
  in-progress human fix by reverting it via `UpdateStack`.
- Never let a repair or drift Lambda touch KMS key policies, Guardrail
  configuration, or the break-glass role under any condition, incident or
  not (§8, §14) — these three are hard-coded exclusions in
  `drift/detector.py`'s `_NEVER_AUTO_REMEDIATE_LOGICAL_HINTS`, not a
  runtime toggle.

## 7. Quarterly game day

Run `agents/scripts/gameday_failover.py` quarterly (§9: "Failover is
exercised quarterly during game day"). It is a real, runnable dry-run: it
reports the actual state of every §9 signal available in the current AWS
account (Route 53 health check status, DDB global-table replica status)
and clearly marks anything not yet provisioned as `NOT_PROVISIONED` rather
than fabricating a result. Escalate `NOT_PROVISIONED` findings to whoever
owns standing up the standby region.
