from __future__ import annotations

from iam_sentinel_adapters.security_hub.asff_mapper import AsffFindingInput, finding_to_asff


def _finding(**overrides: object) -> AsffFindingInput:
    defaults: dict[str, object] = {
        "finding_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "feature_id": "F1",
        "account_id": "111122223333",
        "severity": "HIGH",
        "title": "PassRole blast radius exceeds threshold",
        "detail": "Role X can PassRole into 12 other roles with admin access.",
        "aws_doc_citation_quote": "PassRole is not an API call.",
        "principal_arn": "arn:aws:iam::111122223333:role/Example",
    }
    defaults.update(overrides)
    return AsffFindingInput(**defaults)  # type: ignore[arg-type]


def test_required_top_level_fields_are_present() -> None:
    asff = finding_to_asff(
        _finding(), region="us-east-1", security_hub_account_id="999988887777", updated_at="2026-07-30T00:00:00Z"
    )

    for field in ("SchemaVersion", "Id", "ProductArn", "GeneratorId", "AwsAccountId", "Types", "Severity", "Title", "Description", "Resources"):
        assert field in asff

    assert asff["SchemaVersion"] == "2018-10-08"
    assert asff["Id"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert asff["ProductArn"] == (
        "arn:aws:securityhub:us-east-1:999988887777:product/999988887777/iam-sentinel"
    )
    assert asff["GeneratorId"] == "iam-sentinel/F1"


def test_severity_info_maps_to_informational_label() -> None:
    asff = finding_to_asff(
        _finding(severity="INFO"), region="us-east-1", security_hub_account_id="999988887777", updated_at="t"
    )
    assert asff["Severity"] == {"Label": "INFORMATIONAL", "Normalized": 0}


def test_f5_maps_to_credential_access_type() -> None:
    asff = finding_to_asff(
        _finding(feature_id="F5"), region="us-east-1", security_hub_account_id="999988887777", updated_at="t"
    )
    assert asff["Types"] == ["TTPs/Credential Access"]


def test_f2_maps_to_data_exposure_type() -> None:
    asff = finding_to_asff(
        _finding(feature_id="F2"), region="us-east-1", security_hub_account_id="999988887777", updated_at="t"
    )
    assert asff["Types"] == ["Effects/Data Exposure"]


def test_principal_arn_resource_is_typed_as_iam_role() -> None:
    asff = finding_to_asff(
        _finding(principal_arn="arn:aws:iam::111122223333:role/Example", resource_arn=None),
        region="us-east-1",
        security_hub_account_id="999988887777",
        updated_at="t",
    )
    assert asff["Resources"] == [{"Type": "AwsIamRole", "Id": "arn:aws:iam::111122223333:role/Example"}]


def test_no_principal_falls_back_to_account_resource() -> None:
    asff = finding_to_asff(
        _finding(principal_arn=None, resource_arn=None, account_id="111122223333"),
        region="us-east-1",
        security_hub_account_id="999988887777",
        updated_at="t",
    )
    assert asff["Resources"] == [{"Type": "AwsAccount", "Id": "111122223333"}]


def test_note_cites_the_aws_documentation_quote() -> None:
    asff = finding_to_asff(
        _finding(aws_doc_citation_quote="PassRole is not an API call."),
        region="us-east-1",
        security_hub_account_id="999988887777",
        updated_at="t",
    )
    note = asff["Note"]
    assert isinstance(note, dict)
    assert note["Text"] == "AWS documentation confirms this gap: PassRole is not an API call."


def test_mapping_is_deterministic() -> None:
    finding = _finding()
    first = finding_to_asff(finding, region="us-east-1", security_hub_account_id="999988887777", updated_at="t")
    second = finding_to_asff(finding, region="us-east-1", security_hub_account_id="999988887777", updated_at="t")
    assert first == second
