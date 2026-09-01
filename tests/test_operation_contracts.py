from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from codex_session_manager.models import OperationName
from codex_session_manager.operation_contracts import evaluate_operation_contracts

METHODS = {
    "initialize",
    "thread/list",
    "thread/read",
    "thread/loaded/list",
    "thread/archive",
    "thread/unarchive",
    "thread/turns/list",
}


def _object_document(
    title: str,
    properties: dict[str, dict[str, Any]],
    *,
    required: tuple[str, ...] = (),
    definitions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "title": title,
        "type": "object",
        "properties": properties,
    }
    if required:
        document["required"] = list(required)
    if definitions:
        document["definitions"] = definitions
    return document


def _array(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


def _nullable_string() -> dict[str, Any]:
    return {"type": ["string", "null"]}


def _thread_definition() -> dict[str, Any]:
    turn = {
        "type": "object",
        "required": ["id", "status", "items"],
        "properties": {
            "id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["completed", "interrupted", "failed", "inProgress"],
            },
            "items": _array({"type": "object"}),
        },
    }
    return {
        "type": "object",
        "required": ["id", "status", "createdAt", "updatedAt", "ephemeral", "turns"],
        "properties": {
            "id": {"type": "string"},
            "createdAt": {"type": ["integer", "null"]},
            "updatedAt": {"type": ["integer", "null"]},
            "status": {
                "type": "object",
                "required": ["type"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["notLoaded", "idle", "active", "systemError"],
                    }
                },
            },
            "parentThreadId": _nullable_string(),
            "forkedFromId": _nullable_string(),
            "sessionId": {"type": "string"},
            "ephemeral": {"type": "boolean"},
            "historyMode": {"type": "string", "enum": ["legacy", "paginated"]},
            "turns": _array({"$ref": "#/definitions/Turn"}),
        },
    }, {
        "Turn": turn,
    }


def _baseline_documents() -> dict[str, dict[str, Any]]:
    thread, turn_definition = _thread_definition()
    return {
        "ClientRequest.json": {"title": "ClientRequest", "type": "object"},
        "v2/ThreadListParams.json": _object_document(
            "ThreadListParams",
            {
                "archived": {"type": ["boolean", "null"]},
                "cursor": _nullable_string(),
                "limit": {"type": ["integer", "null"]},
                "sourceKinds": _array({"type": "string"}),
                "useStateDbOnly": {"type": "boolean"},
            },
        ),
        "v2/ThreadReadParams.json": _object_document(
            "ThreadReadParams",
            {"threadId": {"type": "string"}, "includeTurns": {"type": "boolean"}},
            required=("threadId",),
        ),
        "v2/ThreadLoadedListParams.json": _object_document(
            "ThreadLoadedListParams",
            {"cursor": _nullable_string(), "limit": {"type": ["integer", "null"]}},
        ),
        "v2/ThreadArchiveParams.json": _object_document(
            "ThreadArchiveParams", {"threadId": {"type": "string"}}, required=("threadId",)
        ),
        "v2/ThreadUnarchiveParams.json": _object_document(
            "ThreadUnarchiveParams", {"threadId": {"type": "string"}}, required=("threadId",)
        ),
        "v2/ThreadTurnsListParams.json": _object_document(
            "ThreadTurnsListParams",
            {
                "threadId": {"type": "string"},
                "cursor": _nullable_string(),
                "limit": {"type": ["integer", "null"]},
                "sortDirection": {"type": "string", "enum": ["asc", "desc"]},
                "itemsView": {"type": "string", "enum": ["full", "summary"]},
            },
            required=("threadId",),
        ),
        "v2/ThreadListResponse.json": _object_document(
            "ThreadListResponse",
            {
                "data": _array({"$ref": "#/definitions/Thread"}),
                "nextCursor": _nullable_string(),
            },
            required=("data",),
            definitions={"Thread": thread, **turn_definition},
        ),
        "v2/ThreadReadResponse.json": _object_document(
            "ThreadReadResponse",
            {"thread": {"$ref": "#/definitions/Thread"}},
            required=("thread",),
            definitions={"Thread": thread, **turn_definition},
        ),
        "v2/ThreadLoadedListResponse.json": _object_document(
            "ThreadLoadedListResponse",
            {
                "data": _array({"type": "string"}),
                "threadIds": _array({"type": "string"}),
            },
        ),
        "v2/ThreadTurnsListResponse.json": _object_document(
            "ThreadTurnsListResponse",
            {
                "data": _array({"$ref": "#/definitions/Turn"}),
                "nextCursor": _nullable_string(),
            },
            required=("data",),
            definitions={"Turn": turn_definition["Turn"]},
        ),
        "v2/ThreadArchiveResponse.json": {"title": "ThreadArchiveResponse", "type": "object"},
        "v2/ThreadUnarchiveResponse.json": {
            "title": "ThreadUnarchiveResponse",
            "type": "object",
        },
        "v2/ThreadArchivedNotification.json": _object_document(
            "ThreadArchivedNotification", {"threadId": {"type": "string"}}, required=("threadId",)
        ),
        "v2/ThreadUnarchivedNotification.json": _object_document(
            "ThreadUnarchivedNotification", {"threadId": {"type": "string"}}, required=("threadId",)
        ),
    }


def _evaluate(
    stable_documents: dict[str, dict[str, Any]] | None = None,
    *,
    stable_methods: set[str] | None = None,
    experimental_documents: dict[str, dict[str, Any]] | None = None,
    experimental_methods: set[str] | None = None,
    experimental_api: bool = True,
):
    stable = _baseline_documents() if stable_documents is None else stable_documents
    experimental = stable if experimental_documents is None else experimental_documents
    return evaluate_operation_contracts(
        stable_documents=stable,
        experimental_documents=experimental,
        stable_methods=stable_methods or METHODS,
        experimental_methods=experimental_methods or set(),
        experimental_api=experimental_api,
    )


def _by_name(capabilities):
    return {capability.operation: capability for capability in capabilities}


def test_baseline_schema_satisfies_all_five_operation_contracts() -> None:
    capabilities = _by_name(_evaluate())
    assert set(capabilities) == set(OperationName)
    assert all(capability.available for capability in capabilities.values())
    assert [capability.contract_id for capability in capabilities.values()] == [
        "inventory.common.v1",
        "history.legacy.v1",
        "history.paginated.v1",
        "archive.v1",
        "unarchive.v1",
    ]


def test_exact_profile_fixture_is_regression_evidence_only() -> None:
    fixture = Path(__file__).parent / "fixtures" / "exact-protocol-profiles-v1.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    versions = {profile["codex_version"] for profile in payload["profiles"]}
    assert "0.151.0-alpha.7.2" in versions
    assert not (
        Path(__file__).parents[1] / "src/codex_session_manager/protocol_profiles.py"
    ).exists()
    assert not (
        Path(__file__).parents[1] / "src/codex_session_manager/protocol_profiles.json"
    ).exists()


def test_irrelevant_version_schema_document_and_optional_field_do_not_change_contracts() -> None:
    changed = deepcopy(_baseline_documents())
    changed["unrelated.json"] = {"title": "NewThing", "type": "string", "default": "x"}
    changed["v2/ThreadListParams.json"]["properties"]["futureOptional"] = {"type": "object"}
    before = _by_name(_evaluate())
    after = _by_name(_evaluate(changed))
    assert {name: capability.available for name, capability in before.items()} == {
        name: capability.available for name, capability in after.items()
    }
    assert {
        name: capability.runtime_contract_fingerprint for name, capability in before.items()
    } == {name: capability.runtime_contract_fingerprint for name, capability in after.items()}
    assert {name: capability.contract_rule_fingerprint for name, capability in before.items()} == {
        name: capability.contract_rule_fingerprint for name, capability in after.items()
    }


def test_archive_schema_break_only_disables_archive() -> None:
    missing_method = _by_name(_evaluate(stable_methods=METHODS - {"thread/archive"}))
    assert not missing_method[OperationName.ARCHIVE].available
    assert all(
        missing_method[name].available
        for name in OperationName
        if name is not OperationName.ARCHIVE
    )

    changed = deepcopy(_baseline_documents())
    changed["v2/ThreadArchiveParams.json"]["properties"]["threadId"]["type"] = "integer"
    changed_type = _by_name(_evaluate(changed))
    assert not changed_type[OperationName.ARCHIVE].available
    assert all(
        changed_type[name].available for name in OperationName if name is not OperationName.ARCHIVE
    )


def test_paginated_breaks_only_paginated_history() -> None:
    for document_name, field_name, mutation in (
        ("v2/ThreadTurnsListParams.json", "itemsView", lambda field: field["enum"].remove("full")),
        (
            "v2/ThreadTurnsListParams.json",
            "sortDirection",
            lambda field: field["enum"].remove("asc"),
        ),
        (
            "v2/ThreadTurnsListResponse.json",
            "nextCursor",
            lambda field: field.update({"type": "string"}),
        ),
    ):
        changed = deepcopy(_baseline_documents())
        mutation(changed[document_name]["properties"][field_name])
        capabilities = _by_name(_evaluate(changed))
        assert not capabilities[OperationName.HISTORY_PAGINATED].available
        assert capabilities[OperationName.HISTORY_LEGACY].available
        assert capabilities[OperationName.ARCHIVE].available


def test_experimental_paginated_method_requires_negotiation_and_stable_promotion_is_automatic() -> (
    None
):
    stable_methods = METHODS - {"thread/turns/list"}
    only_experimental = _by_name(
        _evaluate(
            stable_methods=stable_methods,
            experimental_methods={"thread/turns/list"},
            experimental_api=False,
        )
    )
    assert not only_experimental[OperationName.HISTORY_PAGINATED].available
    assert any(
        issue.code == "method_stability"
        for issue in only_experimental[OperationName.HISTORY_PAGINATED].issues
    )
    negotiated = _by_name(
        _evaluate(
            stable_methods=stable_methods,
            experimental_methods={"thread/turns/list"},
            experimental_api=True,
        )
    )
    assert negotiated[OperationName.HISTORY_PAGINATED].available
    evidence = negotiated[OperationName.HISTORY_PAGINATED].method_evidence[0]
    assert evidence.stability == "experimental"
    assert evidence.negotiated
    promoted = _by_name(
        _evaluate(
            experimental_documents={
                "v2/ThreadTurnsListParams.json": {"type": "string"},
                "v2/ThreadTurnsListResponse.json": {"type": "string"},
            }
        )
    )
    assert promoted[OperationName.HISTORY_PAGINATED].available
    assert promoted[OperationName.HISTORY_PAGINATED].method_evidence[0].stability == "stable"


def test_missing_document_and_unresolved_ref_return_structured_issues() -> None:
    missing = deepcopy(_baseline_documents())
    del missing["v2/ThreadReadResponse.json"]
    missing_capabilities = _by_name(_evaluate(missing))
    assert not missing_capabilities[OperationName.INVENTORY_COMMON].available
    issue = missing_capabilities[OperationName.INVENTORY_COMMON].issues[0]
    assert issue.code == "document_missing"
    assert "ThreadReadResponse" in issue.subject
    assert issue.actual is None

    unresolved = deepcopy(_baseline_documents())
    unresolved["v2/ThreadListResponse.json"]["properties"]["data"]["items"]["$ref"] = (
        "#/definitions/UnknownThread"
    )
    unresolved_capabilities = _by_name(_evaluate(unresolved))
    assert not unresolved_capabilities[OperationName.INVENTORY_COMMON].available
    assert any(
        issue.code == "reference_unresolved"
        and "ThreadListResponse" in issue.subject
        and issue.actual == "#/definitions/UnknownThread"
        for issue in unresolved_capabilities[OperationName.INVENTORY_COMMON].issues
    )


def test_new_required_unsent_archive_field_blocks_only_archive() -> None:
    changed = deepcopy(_baseline_documents())
    changed["v2/ThreadArchiveParams.json"]["required"].append("newField")
    capabilities = _by_name(_evaluate(changed))
    assert not capabilities[OperationName.ARCHIVE].available
    assert capabilities[OperationName.UNARCHIVE].available
    assert any(issue.code == "requiredness" for issue in capabilities[OperationName.ARCHIVE].issues)


def test_response_unions_reject_an_unrecoverable_branch() -> None:
    for keyword in ("anyOf", "oneOf"):
        changed = deepcopy(_baseline_documents())
        changed["v2/ThreadListResponse.json"]["properties"]["data"] = {
            keyword: [
                {"type": "array", "items": {"$ref": "#/definitions/Thread"}},
                {"type": "string"},
            ]
        }

        capabilities = _by_name(_evaluate(changed))

        assert not capabilities[OperationName.INVENTORY_COMMON].available
        assert not capabilities[OperationName.ARCHIVE].available
        assert capabilities[OperationName.HISTORY_LEGACY].available


def test_request_union_accepts_the_exact_csm_value() -> None:
    changed = deepcopy(_baseline_documents())
    changed["v2/ThreadArchiveParams.json"]["properties"]["threadId"] = {
        "anyOf": [{"type": "integer"}, {"type": "string"}]
    }

    capabilities = _by_name(_evaluate(changed))

    assert capabilities[OperationName.ARCHIVE].available


def test_all_of_applies_all_request_constraints() -> None:
    changed = deepcopy(_baseline_documents())
    changed["v2/ThreadArchiveParams.json"]["properties"]["threadId"] = {
        "allOf": [{"type": "string"}, {"enum": ["not-a-thread-id"]}]
    }

    capabilities = _by_name(_evaluate(changed))

    assert not capabilities[OperationName.ARCHIVE].available
    assert any(issue.code == "schema_combiner" for issue in capabilities[OperationName.ARCHIVE].issues)


def test_enum_presence_is_fail_closed_but_unknown_values_are_compatible() -> None:
    cases = (
        (None, True),
        ([], False),
        ("full", False),
        (["summary"], False),
        (["full", "future"], True),
    )
    for enum, available in cases:
        changed = deepcopy(_baseline_documents())
        field = changed["v2/ThreadTurnsListParams.json"]["properties"]["itemsView"]
        if enum is None:
            field.pop("enum")
        else:
            field["enum"] = enum

        capability = _by_name(_evaluate(changed))[OperationName.HISTORY_PAGINATED]

        assert capability.available is available


def test_cyclic_refs_and_invalid_combiners_fail_closed_without_recursion_error() -> None:
    cyclic = deepcopy(_baseline_documents())
    cyclic["v2/ThreadListResponse.json"]["definitions"]["Thread"] = {
        "$ref": "#/definitions/Thread"
    }
    cyclic_capability = _by_name(_evaluate(cyclic))[OperationName.INVENTORY_COMMON]
    assert not cyclic_capability.available
    assert any(issue.code == "reference_cycle" for issue in cyclic_capability.issues)

    mutual = deepcopy(_baseline_documents())
    mutual["v2/ThreadListResponse.json"]["definitions"]["Thread"] = {
        "$ref": "#/definitions/Other"
    }
    mutual["v2/ThreadListResponse.json"]["definitions"]["Other"] = {
        "$ref": "#/definitions/Thread"
    }
    mutual_capability = _by_name(_evaluate(mutual))[OperationName.INVENTORY_COMMON]
    assert not mutual_capability.available
    assert any(issue.code == "reference_cycle" for issue in mutual_capability.issues)

    invalid = deepcopy(_baseline_documents())
    invalid["v2/ThreadListResponse.json"]["properties"]["data"] = {
        "anyOf": [{"type": "array"}, "not-a-schema"]
    }
    invalid_capability = _by_name(_evaluate(invalid))[OperationName.INVENTORY_COMMON]
    assert not invalid_capability.available
    assert any(issue.code == "schema_branch" for issue in invalid_capability.issues)

    invalid_combiner = deepcopy(_baseline_documents())
    invalid_combiner["v2/ThreadListResponse.json"]["properties"]["data"] = {
        "oneOf": "not-an-array"
    }
    combiner_capability = _by_name(_evaluate(invalid_combiner))[OperationName.INVENTORY_COMMON]
    assert not combiner_capability.available
    assert any(issue.code == "schema_combiner" for issue in combiner_capability.issues)


def test_required_set_changes_runtime_fingerprint_but_not_order() -> None:
    before = _by_name(_evaluate())[OperationName.INVENTORY_COMMON]

    added = deepcopy(_baseline_documents())
    added["v2/ThreadListParams.json"]["required"] = ["archived"]
    after_added = _by_name(_evaluate(added))[OperationName.INVENTORY_COMMON]
    assert after_added.available
    assert after_added.runtime_contract_fingerprint != before.runtime_contract_fingerprint

    reordered = deepcopy(_baseline_documents())
    reordered["v2/ThreadListParams.json"]["required"] = ["limit", "archived"]
    reordered["v2/ThreadLoadedListParams.json"]["required"] = ["limit"]
    first = _by_name(_evaluate(reordered))[OperationName.INVENTORY_COMMON]
    reordered["v2/ThreadListParams.json"]["required"] = ["archived", "limit"]
    second = _by_name(_evaluate(reordered))[OperationName.INVENTORY_COMMON]
    assert first.available and second.available
    assert first.runtime_contract_fingerprint == second.runtime_contract_fingerprint
