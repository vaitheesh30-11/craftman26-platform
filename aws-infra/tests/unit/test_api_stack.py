"""Contract checks for ApiStack (phase-07): the REST API's route/auth
shape, the emergency resource-policy Deny (ADR 0017 decision 3), Cognito's
MFA/advanced-security config, and the WebSocket API's three routes. Live
integration (curl + Cognito token, WebSocket connect/send/receive, a real
WAF block) is deferred per ADR 0017 -- this sandbox has no deployed stage.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import Stack
from aws_cdk.assertions import Match, Template

from iam_sentinel_infra.app_factory import build_app


def _api_template() -> Template:
    app = build_app("dev")
    stack = app.node.find_child("SentinelApi")
    assert isinstance(stack, Stack)
    return Template.from_stack(stack)


def test_health_route_has_no_authorization() -> None:
    template = _api_template()
    template.has_resource_properties(
        "AWS::ApiGateway::Method",
        {"HttpMethod": "GET", "AuthorizationType": "NONE", "ResourceId": Match.any_value()},
    )


def test_catchall_proxy_route_uses_a_custom_lambda_authorizer() -> None:
    template = _api_template()
    template.has_resource_properties(
        "AWS::ApiGateway::Method",
        {
            "HttpMethod": "ANY",
            "AuthorizationType": "CUSTOM",
            "ResourceId": Match.any_value(),
            "AuthorizerId": Match.any_value(),
        },
    )
    template.resource_count_is("AWS::ApiGateway::Authorizer", 1)
    template.has_resource_properties("AWS::ApiGateway::Authorizer", {"Type": "REQUEST"})


def test_emergency_proxy_route_uses_native_iam_authorization() -> None:
    template = _api_template()
    resources = template.find_resources("AWS::ApiGateway::Resource")
    emergency_proxy_ids = {
        logical_id
        for logical_id, props in resources.items()
        if props["Properties"].get("PathPart") == "{proxy+}"
    }
    assert emergency_proxy_ids  # both catch-all and emergency proxies exist

    methods = template.find_resources("AWS::ApiGateway::Method")
    iam_methods = [
        props
        for props in methods.values()
        if props["Properties"].get("AuthorizationType") == "AWS_IAM"
    ]
    assert len(iam_methods) == 1


def test_rest_api_resource_policy_denies_emergency_without_breakglass_tag() -> None:
    template = _api_template()
    rest_apis = template.find_resources("AWS::ApiGateway::RestApi")
    (props,) = rest_apis.values()
    statements = props["Properties"]["Policy"]["Statement"]
    deny_statements = [s for s in statements if s["Effect"] == "Deny"]
    assert len(deny_statements) == 1
    condition = deny_statements[0]["Condition"]["StringNotEquals"]
    assert condition["aws:PrincipalTag/BreakGlass"] == "IAMSentinel-Two-Signer"


def test_cognito_user_pool_requires_mfa_and_enforced_advanced_security() -> None:
    template = _api_template()
    template.has_resource_properties(
        "AWS::Cognito::UserPool",
        {
            "MfaConfiguration": "ON",
            "UserPoolAddOns": {"AdvancedSecurityMode": "ENFORCED"},
            "Policies": Match.object_like(
                {"PasswordPolicy": Match.object_like({"MinimumLength": 14})}
            ),
        },
    )


def test_three_cognito_groups_are_created() -> None:
    template = _api_template()
    groups = template.find_resources("AWS::Cognito::UserPoolGroup")
    group_names = {props["Properties"]["GroupName"] for props in groups.values()}
    assert group_names == {"SentinelAuditors", "SentinelOperators", "SentinelBreakGlassInitiators"}


def test_websocket_api_has_connect_disconnect_and_default_routes() -> None:
    template = _api_template()
    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    route_keys = {props["Properties"]["RouteKey"] for props in routes.values()}
    assert route_keys == {"$connect", "$disconnect", "$default"}

    connect_route = next(
        props for props in routes.values() if props["Properties"]["RouteKey"] == "$connect"
    )
    assert connect_route["Properties"]["AuthorizationType"] == "CUSTOM"


def test_waf_web_acl_has_the_four_documented_rules() -> None:
    template = _api_template()
    web_acls = template.find_resources("AWS::WAFv2::WebACL")
    (props,) = web_acls.values()
    rule_names = {rule["Name"] for rule in props["Properties"]["Rules"]}
    assert rule_names == {
        "AWSManagedRulesCommonRuleSet",
        "AWSManagedRulesKnownBadInputsRuleSet",
        "RateLimitPerIp",
        "PromptInjectionCommonPayloads",
    }
    rate_rule = next(r for r in props["Properties"]["Rules"] if r["Name"] == "RateLimitPerIp")
    assert rate_rule["Statement"]["RateBasedStatement"]["Limit"] == 500

    template.resource_count_is("AWS::WAFv2::WebACLAssociation", 1)


def test_usage_plans_match_the_documented_throttling_tiers() -> None:
    template = _api_template()
    plans = template.find_resources("AWS::ApiGateway::UsagePlan")
    by_name = {
        props["Properties"]["UsagePlanName"]: props["Properties"] for props in plans.values()
    }
    assert by_name["interactive-dev"]["Throttle"] == {"BurstLimit": 20, "RateLimit": 100}
    assert by_name["machine-dev"]["Throttle"] == {"BurstLimit": 5, "RateLimit": 5}


def test_permission_boundary_allows_cognito_getuser_and_manage_connections() -> None:
    app = build_app("dev")
    security_stack = app.node.find_child("SentinelSecurity")
    assert isinstance(security_stack, Stack)
    template = Template.from_stack(security_stack)
    template.has_resource_properties(
        "AWS::IAM::ManagedPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Sid": "AllowApiAuthAndWebSocketFanOut",
                                "Action": ["cognito-idp:GetUser", "execute-api:ManageConnections"],
                            }
                        )
                    ]
                )
            }
        },
    )


def test_backend_lambda_asset_shim_is_present_and_valid_python() -> None:
    """Guards against ADR 0017 decision 4's shim silently going missing or
    being reduced to an unparsable stub."""
    handler_path = Path(__file__).resolve().parents[2] / "functions" / "backend_api" / "handler.py"
    source = handler_path.read_text(encoding="utf-8")
    compile(source, str(handler_path), "exec")
    assert "BACKEND_NOT_PACKAGED" in source


def test_ssm_params_publish_api_and_cognito_identifiers() -> None:
    template = _api_template()
    params = template.find_resources("AWS::SSM::Parameter")
    names = {props["Properties"]["Name"] for props in params.values()}
    assert "/sentinel/dev/api/url" in names
    assert "/sentinel/dev/cognito/user_pool_id" in names
    assert "/sentinel/dev/websocket/url" in names
