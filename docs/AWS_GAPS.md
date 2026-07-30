# The Eight AWS-Confirmed Gaps IAM Sentinel Closes

Every finding IAM Sentinel emits cites one of these AWS documentation quotes as `aws_doc_citation`. The citation is what makes a Sentinel finding un-arguable: AWS itself has said the gap exists.

Order below matches Feature IDs F1..F8.

---

## F1 — PassRole Blast Radius

**Specialist:** PassRole Cartographer.

**AWS confirmed quote (IAM User Guide).**
> "`PassRole` is not an API call. No CloudTrail logs are generated for `iam:PassRole`. The `iam:PassRole` action is not tracked and is not included in IAM action last accessed information. It is not included in generated policies."

**Why it matters.**
A principal with `iam:PassRole` on `*` can hand any role in the account to Lambda, EC2, ECS, Glue, or SageMaker. If any passable role has AdministratorAccess, that principal is effectively admin — with zero audit trail. Access Analyzer produces no finding. Last-accessed data records no signal. Auto-generated least-privilege policies omit PassRole entirely.

**What Sentinel produces.**
A directed graph of `Principal → Role` PassRole edges, scored by reachable privilege in ≤2 hops, with severity CRITICAL/HIGH/MEDIUM/LOW per principal. Every finding cites the quote above.

---

## F2 — Org-Context Policy Validator

**Specialist:** Org Context Validator.

**AWS confirmed quote (IAM Access Analyzer documentation).**
> "Custom policy checks are environment-agnostic in their analysis. Their analysis only considers information contained within the input policies. For example, custom policy checks cannot check whether an account is a member of a specific AWS organization. Therefore, the custom policy checks cannot compare new access based on condition key values for the `aws:PrincipalOrgId` and `aws:PrincipalAccount` condition keys."

**Why it matters.**
Every enterprise uses `aws:PrincipalOrgId` as its primary trust boundary. Policies conditioned on `PrincipalOrgId` are safe — Access Analyzer flags them as publicly accessible anyway because it ignores the condition. Real findings get buried in false-positive noise; security teams stop trusting the tool.

**What Sentinel produces.**
Classification of each Access Analyzer active finding as TRUE_POSITIVE or FALSE_POSITIVE_ORG_SCOPED using real org data (`organizations:DescribeOrganization`, `ListAccounts`, full OU tree), with an auto-archive rule in Access Analyzer for confirmed false positives. Cites the quote above on every archive.

---

## F3 — S3 Data Event Policy Enricher

**Specialist:** Data Event Enricher.

**AWS confirmed quote (IAM Access Analyzer documentation).**
> "Data events not available — IAM Access Analyzer does not identify action-level activity for data events, such as Amazon S3 data events, in generated policies."

**AWS confirmed quote (AWS Well-Architected Framework).**
> "By default, CloudTrail does not log data events such as Amazon S3 object-level activity (`GetObject`, `DeleteObject`)."

**Why it matters.**
`s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` are the most-used S3 actions in production. Access Analyzer's generated policies contain zero S3 data actions, so operators either add `s3:*` (defeating least privilege) or apply the generated policy and break production immediately.

**What Sentinel produces.**
An Athena query over CloudTrail S3 data events, grouped by principal ARN, merged with Access Analyzer's `StartPolicyGeneration` output into a single least-privilege policy — resource-scoped to real prefixes (`arn:aws:s3:::bucket/prefix/*`), with prefix consolidation to stay under the 6,144-byte inline policy cap.

---

## F4 — SCP Change Impact Analyzer

**Specialist:** SCP Impact Analyst.

**AWS confirmed quote (AWS Organizations documentation).**
> "Test SCPs by creating an organizational unit and moving accounts into it."

**Why it matters.**
That is AWS's recommended test path — literally, "make an OU, move accounts, hope you catch it before customers do." `iam:SimulatePrincipalPolicy` does not model OU-level SCP inheritance. No AWS API computes the intersection of multiple inherited SCPs across an OU hierarchy against real historical usage. Result: modifying a production OU SCP routinely breaks CI/CD, GuardDuty SLRs, backups, and monitoring — simultaneously, across dozens of accounts.

**What Sentinel produces.**
Pre-deploy impact report: given a proposed SCP and a target OU/account, walk the OU hierarchy, replay 90 days of successful writes from CloudTrail via Athena, and report per-role blocked-actions with severity + suggested exemptions.

---

## F5 — SSO Emergency Session Killer

**Specialist:** Session Terminator.

**AWS confirmed quote (AWS IAM Identity Center documentation).**
> "Ending an active session for an IAM Identity Center user doesn't end any active IAM role sessions in the AWS Management Console or AWS CLI."

**AWS confirmed quote (AWS re:Post, AWS staff response).**
> "There currently isn't a direct API method to programmatically terminate active sessions for permission sets specifically. AWS hasn't announced when programmatic termination of active sessions for permission sets will be supported."

**Why it matters.**
When credentials are compromised, revoking the SSO session leaves the underlying IAM role session (issued by STS) valid for up to 12 hours. No AWS API stops it.

**What Sentinel produces.**
Fan-out revocation: for a given permission-set or principal, discover the `AWSReservedSSO_{name}_{random}` roles across every assigned account, attach a `Deny *` inline policy conditioned on `aws:TokenIssueTime < now()`, TTL-driven auto-cleanup. Everything logged and Security-Hub-reported.

---

## F6 — Management Account Shadow Guard

**Specialist:** Shadow Guard.

**AWS confirmed quote (AWS Organizations documentation).**
> "SCPs have no effect on users or roles in the management account."

**AWS confirmed quote (AWS prescriptive guidance).**
> "SCPs don't apply to the management account — your production workloads have no SCP guardrails."

**Why it matters.**
The management account is the most powerful account in any org — it controls billing, Organizations, Control Tower, and every member. It is the only account with zero SCP protection. Any principal in the management account can delete the org trail, detach SCPs, or close member accounts with no guardrails.

**What Sentinel produces.**
Continuous ingestion of mgmt-account CloudTrail events; for each write, evaluate whether an equivalent action would be DENIED in a member account by any org SCP. Emit `SHADOW_VIOLATION` findings; generate a weekly report and auto-drafted compensating controls (EventBridge rules) as deployable CDK.

---

## F7 — SCP Collision Resolver

**Specialist:** Collision Resolver.

**AWS confirmed quote (AWS re:Post, AWS staff response).**
> AWS staff have confirmed that AWS's own SCP evaluation documentation contains incorrect examples for multi-layer inheritance across OU hierarchies.

**Why it matters.**
The multi-layer SCP model is so complex that AWS's own docs get it wrong. Operators cannot answer "why is this action denied in this account?" without walking the entire root→OU→account SCP chain by hand.

**What Sentinel produces.**
A correct SCP evaluation engine that walks root→...→account, computes the intersection of all Allow statements and the union of all Deny statements, and returns the effective policy as a single merged JSON. Identifies collision points and generates plain-English explanations plus minimal-fix suggestions.

---

## F8 — SLR Breakage Pre-Scanner

**Specialist:** SLR Guardian.

**AWS confirmed quote (AWS Organizations documentation, paraphrased for scope).**
> SCPs apply to all principals in member accounts, including Service-Linked Roles.

**Why it matters.**
No AWS tool proactively checks whether a proposed SCP will accidentally break AWS Service-Linked Roles (SLRs). A `Deny ec2:TerminateInstances` accidentally breaks Auto Scaling. A `Deny iam:*` accidentally breaks GuardDuty. Break happens after deploy, at 2 AM.

**What Sentinel produces.**
A curated SLR database (service principal → required actions) refreshed weekly from `iam:ListPolicies` scope=AWS. Given a proposed SCP, expand every Deny wildcard, intersect against every SLR's required-actions set, and emit an impact report per SLR (CRITICAL / HIGH / MEDIUM) with drop-in exemption statements or a suggested `aws:PrincipalIsAWSService` condition.

---

## How Findings Cite These Gaps

Every `Finding` produced by any specialist MUST populate `aws_doc_citation` with:

```json
{
  "gap_id": "F1",
  "quote": "PassRole is not an API call. ...",
  "source": "AWS IAM User Guide",
  "url": "https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_generate-policy.html",
  "retrieved_on": "2026-07-30"
}
```

Contract validation in `docs/DATA_CONTRACTS.md#finding` rejects any Finding whose `aws_doc_citation` is missing, whose `gap_id` is not in `{F1..F8}`, or whose `quote` is not present in the ingested corpus (checked at ingest time; specialists cannot invent quotes).
