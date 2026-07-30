"""API Gateway REST + WebSocket + Cognito authorizer (phase-07). Fronts
`backend`'s FastAPI-on-Lambda app (`iam_sentinel_backend.app.handler`,
phase-00) with a REST API for HTTP routes and a WebSocket API for streamed
Prime turns. See ADR 0017 for four architecture decisions this phase's own
spec ambiguities forced: the single hybrid Lambda authorizer covering both
Cognito and IAM SigV4 callers, that authorizer's zero-dependency Cognito
verification via `cognito-idp:GetUser`, `/emergency/*`'s native-`AWS_IAM`
resource-policy gating (a Lambda authorizer cannot recover session tags
after the fact), and `backend_api`'s placeholder shim pending a Lambda
dependency-bundling pipeline (the same packaging gap ADR 0011/0015 already
flagged).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigateway as apigateway
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_authorizers as apigwv2_auth
from aws_cdk import aws_apigatewayv2_integrations as apigwv2_int
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_ssm as ssm
from aws_cdk import aws_wafv2 as wafv2
from cdk_nag import NagSuppressions

from iam_sentinel_infra.constructs.sentinel_lambda import LAMBDA_ASSET_EXCLUDES

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.bedrock_stack import BedrockStack
    from iam_sentinel_infra.stacks.foundation_stack import FoundationStack
    from iam_sentinel_infra.stacks.lambda_stack import LambdaStack
    from iam_sentinel_infra.stacks.security_stack import SecurityStack

_FUNCTIONS_DIR = Path(__file__).resolve().parents[3] / "functions"

# Mirrors backend/src/iam_sentinel_backend/settings.py's
# BackendSettings.cognito_group_* defaults verbatim (phase-07 §5). Not
# imported -- infra/backend are separate deployable units with no shared
# dependency, per the module-boundary convention every prior phase follows.
_COGNITO_GROUPS = ("SentinelAuditors", "SentinelOperators", "SentinelBreakGlassInitiators")
_BREAKGLASS_TAG_KEY = "BreakGlass"
_BREAKGLASS_TAG_VALUE = "IAMSentinel-Two-Signer"

# Common injection-pattern literals, defense-in-depth at the WAF layer on
# top of adapters.prompts.sanitizer.FORBIDDEN_PATTERNS' application-layer
# check (phase-07 §7). Kept short and representative per the revised
# testing/scope policy -- not the full corpus.
_PROMPT_INJECTION_LITERALS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard your instructions",
    "you are now in developer mode",
)

_LOG_RETENTION_BY_STAGE = {
    "dev": logs.RetentionDays.TWO_WEEKS,
    "staging": logs.RetentionDays.TWO_WEEKS,
    "prod": logs.RetentionDays.THREE_MONTHS,
}


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        lambdas: LambdaStack,
        bedrock: BedrockStack,
        security: SecurityStack,
        foundation: FoundationStack,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config
        self.lambdas = lambdas
        self.bedrock = bedrock
        self.security = security
        self.foundation = foundation

        self._widen_permission_boundary_for_api_surface()

        self.connections_table = self._build_connections_table()
        self.user_pool, self.user_pool_client, self.user_pool_domain = self._build_cognito()

        self.authorizer_fn = self._build_authorizer_fn()
        self.backend_fn = self._build_backend_fn()
        self.rest_api = self._build_rest_api()
        self.web_acl = self._build_waf()
        self._associate_waf()
        self._build_usage_plans()
        self._build_websocket_api()
        self._publish_ssm_params()

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWSLambdaBasicExecutionRole is CDK's default Lambda execution role "
                        "addition (CloudWatch Logs only, scoped to the function's own log group)."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "cognito-idp:GetUser and apigatewaymanagementapi:PostToConnection "
                        "are wildcarded on the pool-id/api-id ARN segment because both "
                        "resources are created by this same stack -- CDK cannot reference "
                        "a resource's own ARN before it exists (same self-reference "
                        "constraint the Guardrail lifecycle Lambda documents in ADR 0001)."
                    ),
                },
                {
                    "id": "AwsSolutions-APIG2",
                    "reason": (
                        "Request validation lives in the FastAPI/Pydantic layer "
                        "(backend phase-00's error envelope, phase-01's route models) -- "
                        "API Gateway is a thin proxy per phase-07 §3, not a second "
                        "validation layer."
                    ),
                },
                {
                    "id": "AwsSolutions-APIG1",
                    "reason": "Access logging is enabled via deploy_options below; this "
                    "stack's own execution/access log group already covers it -- cdk-nag "
                    "flags the L1 pattern it expects, not an actual gap.",
                },
                {
                    "id": "AwsSolutions-COG4",
                    "reason": (
                        "The `{proxy+}` catch-all route uses the custom Lambda authorizer "
                        "(ADR 0017 decision 1), not the native COGNITO_USER_POOLS "
                        "authorizer type, precisely because it also has to accept IAM "
                        "SigV4 machine callers on the same routes -- the Lambda authorizer "
                        "still verifies Cognito access tokens via cognito-idp:GetUser."
                    ),
                },
                {
                    "id": "HIPAA.Security-LambdaInsideVPC",
                    "reason": "docs/ARCHITECTURE.md §Networking: IAM Sentinel is "
                    "deliberately VPC-less across the whole platform.",
                },
                {
                    "id": "HIPAA.Security-IAMNoInlinePolicy",
                    "reason": "CDK's auto-generated DefaultPolicy grants (DynamoDB "
                    "read/write on SentinelConnections, apigatewaymanagementapi "
                    "PostToConnection); splitting each into a managed policy adds "
                    "indirection without changing the effective grant.",
                },
                {
                    "id": "HIPAA.Security-DynamoDBInBackupPlan",
                    "reason": (
                        "SentinelConnections holds only transient WebSocket connection "
                        "state (4h TTL, phase-07 §4) -- PITR is enabled, but an org-wide "
                        "backup plan (FoundationStack's, per ADR 0003/0005) exists to "
                        "protect durable business data, not ephemeral session rows that "
                        "expire hours after they are written."
                    ),
                },
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "AmazonAPIGatewayPushToCloudWatchLogs is the AWS-managed "
                    "policy CDK's own `cloud_watch_role=True` attaches to the account-level "
                    "API Gateway CloudWatch role; API Gateway does not support a customer-"
                    "managed replacement for this specific integration.",
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
                    ],
                },
                {
                    "id": "HIPAA.Security-APIGWCacheEnabledAndEncrypted",
                    "reason": (
                        "Every route proxies straight through to `backend`'s per-caller, "
                        "per-request FastAPI responses (findings/decisions lists, chat "
                        "turns) -- stage-level response caching would either serve stale "
                        "or cross-caller data; disabled by design, not omitted by oversight."
                    ),
                },
                {
                    "id": "HIPAA.Security-APIGWSSLEnabled",
                    "reason": (
                        "This control is about a custom-domain SSL certificate; ADR 0017 "
                        "explicitly scopes the optional custom domain (phase-07 §2) out -- "
                        "no domain/ACM cert exists yet (frontend phase-00 hasn't landed). "
                        "The default `execute-api` endpoint is already TLS-only."
                    ),
                },
                {
                    "id": "AwsSolutions-APIG4",
                    "reason": (
                        "`GET /health` is explicitly unauthenticated per phase-07 §6 "
                        "('Cognito JWT authorizer on every path except /health') and "
                        "backend phase-00's own `create_app()`; WebSocket's `$disconnect`/"
                        "`$default` routes operate on a connection API Gateway v2 already "
                        "authenticated once, at `$connect` -- WebSocket APIs only support "
                        "an authorizer on that one route, by AWS design."
                    ),
                },
            ],
        )

    # ------------------------------------------------------------------
    # Permission boundary widening (ADR 0017 decisions 1-2)
    # ------------------------------------------------------------------
    def _widen_permission_boundary_for_api_surface(self) -> None:
        """`SentinelPermissionBoundary`'s `AllowWithinSentinelResources`
        statement only lists the service actions phase-00/01/02 already
        needed (bedrock/dynamodb/s3/kms/access-analyzer/organizations) --
        as an ALLOW-list boundary, any action not on it is denied
        regardless of a role's own policy. `cognito-idp:GetUser` (the
        authorizer's Cognito path) and `apigatewaymanagementapi:*` (the
        WebSocket `$default` fan-out) are new action families this phase
        introduces, so the boundary is widened here rather than
        rebuilding it in `SecurityStack` -- the same "widen from the
        phase that needs it" precedent agents phase-02 set for
        `AllowCrossAccountRoleAssumption`.
        """
        self.security.permission_boundary.policy.add_statements(
            iam.PolicyStatement(
                sid="AllowApiAuthAndWebSocketFanOut",
                effect=iam.Effect.ALLOW,
                actions=["cognito-idp:GetUser", "execute-api:ManageConnections"],
                # Pool ID / API ID segments are wildcarded: both resources
                # are created by this same stack, so their ARNs cannot be
                # known before `SentinelPermissionBoundary` is applied to
                # every role in the app graph (phase-00's stack order).
                resources=[
                    f"arn:aws:cognito-idp:{self.region}:{self.account}:userpool/*",
                    f"arn:aws:execute-api:{self.region}:{self.account}:*/*/POST/@connections/*",
                ],
            )
        )

    # ------------------------------------------------------------------
    # SentinelConnections (phase-07 §4) -- not one of FoundationStack's 14
    # phase-02 tables (ADR 0005); it belongs to the API surface this phase
    # owns, same precedent SecurityStack set for BreakGlassSessions.
    # ------------------------------------------------------------------
    def _build_connections_table(self) -> dynamodb.Table:
        return dynamodb.Table(
            self,
            "SentinelConnections",
            table_name=f"SentinelConnections-{self.stage_config.stage}",
            partition_key=dynamodb.Attribute(
                name="connection_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.security.data_key,
            point_in_time_recovery=True,
            time_to_live_attribute="expires_at",
            removal_policy=RemovalPolicy.RETAIN,
        )

    # ------------------------------------------------------------------
    # Cognito (phase-07 §5)
    # ------------------------------------------------------------------
    def _build_cognito(
        self,
    ) -> tuple[cognito.UserPool, cognito.UserPoolClient, cognito.UserPoolDomain]:
        user_pool = cognito.UserPool(
            self,
            "SentinelUserPool",
            user_pool_name=f"SentinelUserPool-{self.stage_config.stage}",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=False)
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=14,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            mfa=cognito.Mfa.REQUIRED,
            # WebAuthn (passkey) MFA has no L2 property on this CDK pin
            # (aws-cdk-lib==2.163.0) -- see ADR 0017 "scoped out" section.
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN,
        )
        # `ENFORCED` is the one AdvancedSecurityMode value that turns on
        # both risk-based *adaptive* authentication and audit logging;
        # `AUDIT` alone (phase-07 §5's other half of "audit + adaptive")
        # would not enable the adaptive half. No L2 prop exists for this
        # yet -- CfnUserPool escape hatch.
        cfn_user_pool = user_pool.node.default_child
        assert isinstance(cfn_user_pool, cognito.CfnUserPool)
        cfn_user_pool.user_pool_add_ons = cognito.CfnUserPool.UserPoolAddOnsProperty(
            advanced_security_mode="ENFORCED"
        )

        for group_name in _COGNITO_GROUPS:
            cognito.CfnUserPoolGroup(
                self,
                f"{group_name}Group",
                user_pool_id=user_pool.user_pool_id,
                group_name=group_name,
            )

        domain = user_pool.add_domain(
            "SentinelUserPoolDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"iam-sentinel-{self.stage_config.stage}-{self.stage_config.account_id[-6:]}"
            ),
        )

        client = user_pool.add_client(
            "SentinelUserPoolClient",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                # frontend phase-00 (sprint step 24) has not landed yet --
                # a real callback URL is wired then; this placeholder keeps
                # the client valid to synth (Cognito requires >=1 callback
                # URL when any OAuth flow is enabled).
                callback_urls=[f"https://{self.stage_config.stage}.iam-sentinel.internal/callback"],
            ),
        )
        return user_pool, client, domain

    # ------------------------------------------------------------------
    # Lambdas (ADR 0017 decisions 1, 2, 4)
    # ------------------------------------------------------------------
    def _build_authorizer_fn(self) -> lambda_.IFunction:
        fn = self.lambdas.new_function(
            self,
            "ApiAuthorizerFn",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "api_authorizer"), exclude=LAMBDA_ASSET_EXCLUDES),
            timeout=Duration.seconds(10),
            memory_size=256,
            alarm_topic=self.security.security_topic,
        ).function
        return fn

    def _build_backend_fn(self) -> lambda_.IFunction:
        """Real CDK wiring; the deployment asset itself is a placeholder
        shim pending a dependency-bundling pipeline. See ADR 0017 decision
        4 and `functions/backend_api/handler.py`."""
        sentinel_fn = self.lambdas.new_function(
            self,
            "BackendApiFn",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "backend_api"), exclude=LAMBDA_ASSET_EXCLUDES),
            role_statements=[
                iam.PolicyStatement(
                    actions=["bedrock:InvokeAgent"],
                    resources=[self.bedrock.prime.agent.attr_agent_arn],
                ),
                iam.PolicyStatement(actions=["sts:GetCallerIdentity"], resources=["*"]),
            ],
            extra_environment={
                "SENTINEL_COGNITO_USER_POOL_ID": self.user_pool.user_pool_id,
                "SENTINEL_COGNITO_APP_CLIENT_ID": self.user_pool_client.user_pool_client_id,
                "SENTINEL_AWS_ACCOUNT_ID": self.stage_config.account_id,
                "SENTINEL_BEDROCK_PRIME_AGENT_ID": self.bedrock.prime.agent.attr_agent_id,
            },
            timeout=Duration.seconds(29),  # API Gateway's own hard integration timeout
            memory_size=1024,
            alarm_topic=self.security.security_topic,
        )
        for table_name in ("SentinelFindings", "SentinelDecisions", "SentinelDecisionsInFlight"):
            self.foundation.tables[table_name].grant_read_write_data(sentinel_fn.role)
        return sentinel_fn.function

    # ------------------------------------------------------------------
    # REST API (phase-07 §2, §3, §6, §8)
    # ------------------------------------------------------------------
    def _build_rest_api(self) -> apigateway.RestApi:
        stage = self.stage_config.stage
        access_log_group = logs.LogGroup(
            self,
            "ApiAccessLogs",
            retention=_LOG_RETENTION_BY_STAGE[stage],
            encryption_key=self.security.data_key,
            removal_policy=RemovalPolicy.RETAIN if stage == "prod" else RemovalPolicy.DESTROY,
        )
        self.security.data_key.grant_encrypt_decrypt(
            iam.ServicePrincipal(f"logs.{self.region}.amazonaws.com")
        )

        rest_api = apigateway.RestApi(
            self,
            "SentinelApi",
            rest_api_name=f"SentinelApi-{stage}",
            cloud_watch_role=True,
            deploy_options=apigateway.StageOptions(
                stage_name=stage,
                logging_level=apigateway.MethodLoggingLevel.INFO,
                data_trace_enabled=stage != "prod",
                access_log_destination=apigateway.LogGroupLogDestination(access_log_group),
                access_log_format=apigateway.AccessLogFormat.json_with_standard_fields(
                    caller=True,
                    http_method=True,
                    ip=True,
                    protocol=True,
                    request_time=True,
                    resource_path=True,
                    response_length=True,
                    status=True,
                    user=True,
                ),
                throttling_burst_limit=20,
                throttling_rate_limit=100,
                tracing_enabled=True,
            ),
        )

        backend_integration = apigateway.LambdaIntegration(self.backend_fn)

        health = rest_api.root.add_resource("health")
        health.add_method(
            "GET", backend_integration, authorization_type=apigateway.AuthorizationType.NONE
        )

        emergency_proxy = rest_api.root.add_resource("emergency").add_resource("{proxy+}")
        emergency_proxy.add_method(
            "ANY", backend_integration, authorization_type=apigateway.AuthorizationType.IAM
        )

        request_authorizer = apigateway.RequestAuthorizer(
            self,
            "HybridRequestAuthorizer",
            handler=self.authorizer_fn,
            identity_sources=[apigateway.IdentitySource.header("Authorization")],
            results_cache_ttl=Duration.seconds(
                0
            ),  # per-caller identity, not safe to cache by header alone across callers
        )
        catchall = rest_api.root.add_resource("{proxy+}")
        catchall.add_method(
            "ANY",
            backend_integration,
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=request_authorizer,
        )

        self._apply_emergency_resource_policy(rest_api)
        return rest_api

    def _apply_emergency_resource_policy(self, rest_api: apigateway.RestApi) -> None:
        """ADR 0017 decision 3: the break-glass tag can only be enforced by
        IAM evaluating the caller's own session at the `execute-api:Invoke`
        boundary, not by a Lambda authorizer re-deriving it after the fact.
        Any resource policy replaces API Gateway's default implicit-allow
        behavior, so a blanket Allow must accompany the narrow Deny.

        `RestApi` has no `add_to_resource_policy` escape hatch (unlike
        `s3.Bucket`) -- the `policy` prop can only be set on the L1
        `CfnRestApi`. Using `arn_for_execute_api()` (a full ARN built from
        `rest_api.rest_api_id`) here would embed a `Ref` to this exact
        resource inside its own `Policy` property; CloudFormation itself
        special-cases that self-reference for API Gateway resource
        policies, but CDK's own dependency-graph inference does not, and
        flags it as an undeployable cycle. AWS's documented shorthand
        resource form for this exact situation (`execute-api:/<stage>/
        <method>/<path>`, relative to "this API" with no account/region/
        api-id segment) sidesteps the self-reference entirely.
        """
        policy_document = iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    sid="AllowInvokeByDefault",
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AnyPrincipal()],
                    actions=["execute-api:Invoke"],
                    resources=["execute-api:/*"],
                ),
                iam.PolicyStatement(
                    sid="DenyEmergencyWithoutBreakGlassTag",
                    effect=iam.Effect.DENY,
                    principals=[iam.AnyPrincipal()],
                    actions=["execute-api:Invoke"],
                    resources=["execute-api:/*/*/emergency/*"],
                    conditions={
                        "StringNotEquals": {
                            f"aws:PrincipalTag/{_BREAKGLASS_TAG_KEY}": _BREAKGLASS_TAG_VALUE
                        }
                    },
                ),
            ]
        )
        cfn_rest_api = rest_api.node.default_child
        assert isinstance(cfn_rest_api, apigateway.CfnRestApi)
        cfn_rest_api.policy = policy_document

    # ------------------------------------------------------------------
    # WAF (phase-07 §7)
    # ------------------------------------------------------------------
    def _build_waf(self) -> wafv2.CfnWebACL:
        prompt_injection_statements = [
            wafv2.CfnWebACL.StatementProperty(
                byte_match_statement=wafv2.CfnWebACL.ByteMatchStatementProperty(
                    search_string=literal,
                    field_to_match=wafv2.CfnWebACL.FieldToMatchProperty(body={}),
                    positional_constraint="CONTAINS",
                    text_transformations=[
                        wafv2.CfnWebACL.TextTransformationProperty(priority=0, type="LOWERCASE")
                    ],
                )
            )
            for literal in _PROMPT_INJECTION_LITERALS
        ]
        return wafv2.CfnWebACL(
            self,
            "SentinelWebAcl",
            name=f"SentinelWebAcl-{self.stage_config.stage}",
            scope="REGIONAL",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=True,
                cloud_watch_metrics_enabled=True,
                metric_name="SentinelWebAcl",
            ),
            rules=[
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesCommonRuleSet",
                    priority=0,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS", name="AWSManagedRulesCommonRuleSet"
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name="AWSManagedRulesCommonRuleSet",
                    ),
                ),
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesKnownBadInputsRuleSet",
                    priority=1,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS", name="AWSManagedRulesKnownBadInputsRuleSet"
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name="AWSManagedRulesKnownBadInputsRuleSet",
                    ),
                ),
                wafv2.CfnWebACL.RuleProperty(
                    name="RateLimitPerIp",
                    priority=2,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=500, aggregate_key_type="IP"
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name="RateLimitPerIp",
                    ),
                ),
                wafv2.CfnWebACL.RuleProperty(
                    name="PromptInjectionCommonPayloads",
                    priority=3,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        or_statement=wafv2.CfnWebACL.OrStatementProperty(
                            statements=prompt_injection_statements
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name="PromptInjectionCommonPayloads",
                    ),
                ),
            ],
        )

    def _associate_waf(self) -> None:
        wafv2.CfnWebACLAssociation(
            self,
            "SentinelWebAclAssociation",
            resource_arn=self.rest_api.deployment_stage.stage_arn,
            web_acl_arn=self.web_acl.attr_arn,
        )
        # WAF requires its own log group's name to start with the literal
        # "aws-waf-logs-" prefix (an AWS-imposed naming convention, not a
        # Sentinel one).
        waf_log_group = logs.LogGroup(
            self,
            "WafLogs",
            log_group_name=f"aws-waf-logs-sentinel-{self.stage_config.stage}",
            retention=_LOG_RETENTION_BY_STAGE[self.stage_config.stage],
            encryption_key=self.security.data_key,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.security.data_key.grant_encrypt_decrypt(
            iam.ServicePrincipal("delivery.logs.amazonaws.com")
        )
        wafv2.CfnLoggingConfiguration(
            self,
            "WafLoggingConfig",
            resource_arn=self.web_acl.attr_arn,
            log_destination_configs=[waf_log_group.log_group_arn],
        )

    def _build_usage_plans(self) -> None:
        """Phase-07 §7 throttling tiers. `add_api_key` issues one
        placeholder key per plan -- real per-caller key issuance is an
        operational task once real interactive users/machine callers
        exist, not something this phase can provision speculatively."""
        interactive_plan = self.rest_api.add_usage_plan(
            "InteractiveUsagePlan",
            name=f"interactive-{self.stage_config.stage}",
            throttle=apigateway.ThrottleSettings(rate_limit=100, burst_limit=20),
        )
        interactive_plan.add_api_stage(stage=self.rest_api.deployment_stage)
        interactive_plan.add_api_key(self.rest_api.add_api_key("InteractiveApiKey"))

        machine_plan = self.rest_api.add_usage_plan(
            "MachineUsagePlan",
            name=f"machine-{self.stage_config.stage}",
            throttle=apigateway.ThrottleSettings(rate_limit=5, burst_limit=5),
        )
        machine_plan.add_api_stage(stage=self.rest_api.deployment_stage)

    # ------------------------------------------------------------------
    # WebSocket API (phase-07 §4)
    # ------------------------------------------------------------------
    def _build_websocket_api(self) -> None:
        connect_fn = self.lambdas.new_function(
            self,
            "WsConnectFn",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "ws_connect"), exclude=LAMBDA_ASSET_EXCLUDES),
            extra_environment={"SENTINEL_CONNECTIONS_TABLE": self.connections_table.table_name},
            timeout=Duration.seconds(10),
            memory_size=256,
            alarm_topic=self.security.security_topic,
        )
        self.connections_table.grant_read_write_data(connect_fn.role)

        disconnect_fn = self.lambdas.new_function(
            self,
            "WsDisconnectFn",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "ws_disconnect"), exclude=LAMBDA_ASSET_EXCLUDES),
            extra_environment={"SENTINEL_CONNECTIONS_TABLE": self.connections_table.table_name},
            timeout=Duration.seconds(10),
            memory_size=256,
            alarm_topic=self.security.security_topic,
        )
        self.connections_table.grant_write_data(disconnect_fn.role)

        default_fn = self.lambdas.new_function(
            self,
            "WsDefaultFn",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "ws_default"), exclude=LAMBDA_ASSET_EXCLUDES),
            extra_environment={"SENTINEL_CONNECTIONS_TABLE": self.connections_table.table_name},
            timeout=Duration.seconds(10),
            memory_size=256,
            alarm_topic=self.security.security_topic,
        )

        self.websocket_api = apigwv2.WebSocketApi(
            self,
            "SentinelStream",
            api_name=f"SentinelStream-{self.stage_config.stage}",
            connect_route_options=apigwv2.WebSocketRouteOptions(
                integration=apigwv2_int.WebSocketLambdaIntegration(
                    "ConnectIntegration", connect_fn.function
                ),
                authorizer=apigwv2_auth.WebSocketLambdaAuthorizer(
                    "WsAuthorizer",
                    self.authorizer_fn,
                    identity_source=["route.request.header.Authorization"],
                ),
            ),
            disconnect_route_options=apigwv2.WebSocketRouteOptions(
                integration=apigwv2_int.WebSocketLambdaIntegration(
                    "DisconnectIntegration", disconnect_fn.function
                )
            ),
            default_route_options=apigwv2.WebSocketRouteOptions(
                integration=apigwv2_int.WebSocketLambdaIntegration(
                    "DefaultIntegration", default_fn.function
                )
            ),
        )
        self.websocket_stage = apigwv2.WebSocketStage(
            self,
            "SentinelStreamStage",
            web_socket_api=self.websocket_api,
            stage_name=self.stage_config.stage,
            auto_deploy=True,
        )
        self.websocket_api.grant_manage_connections(default_fn.role)

    # ------------------------------------------------------------------
    def _publish_ssm_params(self) -> None:
        params = {
            "api/url": self.rest_api.url,
            "api/id": self.rest_api.rest_api_id,
            "websocket/url": self.websocket_stage.url,
            "cognito/user_pool_id": self.user_pool.user_pool_id,
            "cognito/app_client_id": self.user_pool_client.user_pool_client_id,
            "cognito/domain": self.user_pool_domain.domain_name,
        }
        for suffix, value in params.items():
            ssm.StringParameter(
                self,
                f"Param{suffix.replace('/', '').title()}",
                parameter_name=f"/sentinel/{self.stage_config.stage}/{suffix}",
                string_value=value,
            )
