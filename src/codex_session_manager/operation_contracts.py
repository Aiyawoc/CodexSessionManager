"""Minimal, operation-specific checks for the generated App Server schema."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from typing import Any, Final

from codex_session_manager.hashing import fingerprint
from codex_session_manager.models import (
    ContractIssue,
    ContractMethodEvidence,
    OperationCapability,
    OperationName,
)

__all__ = ["evaluate_operation_contracts"]


@dataclass(frozen=True, slots=True)
class _FieldRule:
    document: str
    path: tuple[str, ...]
    types: tuple[str, ...] = ()
    required_types: tuple[str, ...] = ()
    item_types: tuple[str, ...] = ()
    enum_contains: tuple[str, ...] = ()
    required: bool | None = None
    allow_missing: bool = False
    group: str | None = None


@dataclass(frozen=True, slots=True)
class _RequestRule:
    document: str
    fields: tuple[_FieldRule, ...]
    supported_required_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DocumentRule:
    document: str
    types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ContractRule:
    operation: OperationName
    contract_id: str
    methods: tuple[str, ...]
    request_rules: tuple[_RequestRule, ...] = ()
    document_rules: tuple[_DocumentRule, ...] = ()
    fields: tuple[_FieldRule, ...] = ()
    experimental_documents: bool = False
    experimental_method: bool = False


@dataclass(frozen=True, slots=True)
class _Projection:
    types: frozenset[str] = frozenset()
    enums: frozenset[str] = frozenset()
    item_types: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _FieldResult:
    projection: _Projection
    present: bool
    required: bool


def _field(
    document: str,
    *path: str,
    types: tuple[str, ...] = (),
    required_types: tuple[str, ...] = (),
    item_types: tuple[str, ...] = (),
    enum_contains: tuple[str, ...] = (),
    required: bool | None = None,
    allow_missing: bool = False,
    group: str | None = None,
) -> _FieldRule:
    return _FieldRule(
        document=document,
        path=path,
        types=types,
        required_types=required_types,
        item_types=item_types,
        enum_contains=enum_contains,
        required=required,
        allow_missing=allow_missing,
        group=group,
    )


_STRING: Final[tuple[str, ...]] = ("string",)
_STRING_OR_NULL: Final[tuple[str, ...]] = ("string", "null")
_ARRAY: Final[tuple[str, ...]] = ("array",)
_OBJECT: Final[tuple[str, ...]] = ("object",)

_THREAD_FIELDS: Final[tuple[_FieldRule, ...]] = (
    _field("v2/ThreadListResponse.json", "data", "[]", "id", types=_STRING, required=True),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "createdAt",
        types=("integer", "number", "string"),
        required=True,
    ),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "updatedAt",
        types=("integer", "number", "string"),
        required=True,
    ),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "status",
        types=_OBJECT,
        required=True,
    ),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "status",
        "type",
        types=_STRING,
        enum_contains=("notLoaded", "idle", "active", "systemError"),
        required=True,
    ),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "parentThreadId",
        types=_STRING_OR_NULL,
    ),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "forkedFromId",
        types=_STRING_OR_NULL,
    ),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "sessionId",
        types=_STRING_OR_NULL,
    ),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "ephemeral",
        types=("boolean",),
        required=True,
    ),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "historyMode",
        types=_STRING,
        enum_contains=("legacy", "paginated"),
        allow_missing=True,
    ),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "turns",
        types=_ARRAY,
        item_types=_OBJECT,
        required=True,
    ),
)

_THREAD_READ_FIELDS: Final[tuple[_FieldRule, ...]] = tuple(
    replace(
        field,
        document="v2/ThreadReadResponse.json",
        path=("thread", *field.path[2:]),
    )
    for field in _THREAD_FIELDS
)

_TURN_FIELDS: Final[tuple[_FieldRule, ...]] = (
    _field(
        "v2/ThreadTurnsListResponse.json",
        "data",
        "[]",
        "id",
        types=_STRING,
        required=True,
    ),
    _field(
        "v2/ThreadTurnsListResponse.json",
        "data",
        "[]",
        "status",
        types=_STRING,
        enum_contains=("completed", "interrupted", "failed", "inProgress"),
        required=True,
    ),
    _field(
        "v2/ThreadTurnsListResponse.json",
        "data",
        "[]",
        "items",
        types=_ARRAY,
        item_types=_OBJECT,
        required=True,
    ),
)

_LEGACY_TURN_FIELDS: Final[tuple[_FieldRule, ...]] = (
    _field(
        "v2/ThreadReadResponse.json",
        "thread",
        "turns",
        "[]",
        "id",
        types=_STRING,
        required=True,
    ),
    _field(
        "v2/ThreadReadResponse.json",
        "thread",
        "turns",
        "[]",
        "status",
        types=_STRING,
        enum_contains=("completed", "interrupted", "failed", "inProgress"),
        required=True,
    ),
    _field(
        "v2/ThreadReadResponse.json",
        "thread",
        "turns",
        "[]",
        "items",
        types=_ARRAY,
        item_types=_OBJECT,
        required=True,
    ),
)

_COMMON_FIELDS: Final[tuple[_FieldRule, ...]] = (
    _field(
        "v2/ThreadListParams.json",
        "archived",
        types=("boolean",),
    ),
    _field("v2/ThreadListParams.json", "cursor", types=_STRING_OR_NULL),
    _field("v2/ThreadListParams.json", "limit", types=("integer",)),
    _field(
        "v2/ThreadListParams.json",
        "sourceKinds",
        types=_ARRAY,
        item_types=_STRING,
    ),
    _field("v2/ThreadListParams.json", "useStateDbOnly", types=("boolean",)),
    _field(
        "v2/ThreadReadParams.json",
        "threadId",
        types=_STRING,
        required=True,
    ),
    _field("v2/ThreadReadParams.json", "includeTurns", types=("boolean",)),
    _field("v2/ThreadLoadedListParams.json", "cursor", types=_STRING_OR_NULL),
    _field("v2/ThreadLoadedListParams.json", "limit", types=("integer",)),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        types=_ARRAY,
        item_types=_OBJECT,
        required=True,
    ),
    _field(
        "v2/ThreadListResponse.json",
        "nextCursor",
        types=_STRING_OR_NULL,
        required_types=_STRING_OR_NULL,
    ),
    _field(
        "v2/ThreadReadResponse.json",
        "thread",
        types=_OBJECT,
        required=True,
    ),
    _field(
        "v2/ThreadLoadedListResponse.json",
        "data",
        types=_ARRAY,
        item_types=_STRING,
        group="loaded_ids",
        allow_missing=True,
    ),
    _field(
        "v2/ThreadLoadedListResponse.json",
        "threadIds",
        types=_ARRAY,
        item_types=_STRING,
        group="loaded_ids",
        allow_missing=True,
    ),
)

_COMMON_REQUESTS: Final[tuple[_RequestRule, ...]] = (
    _RequestRule(
        "v2/ThreadListParams.json",
        tuple(
            field for field in _COMMON_FIELDS if field.document.endswith("ThreadListParams.json")
        ),
        ("archived", "cursor", "limit", "sourceKinds", "useStateDbOnly"),
    ),
    _RequestRule(
        "v2/ThreadReadParams.json",
        tuple(
            field for field in _COMMON_FIELDS if field.document.endswith("ThreadReadParams.json")
        ),
        ("threadId", "includeTurns"),
    ),
    _RequestRule(
        "v2/ThreadLoadedListParams.json",
        tuple(
            field
            for field in _COMMON_FIELDS
            if field.document.endswith("ThreadLoadedListParams.json")
        ),
        ("cursor", "limit"),
    ),
)

_COMMON_DOCUMENTS: Final[tuple[_DocumentRule, ...]] = (
    _DocumentRule("v2/ThreadListResponse.json", _OBJECT),
    _DocumentRule("v2/ThreadReadResponse.json", _OBJECT),
    _DocumentRule("v2/ThreadLoadedListResponse.json", _OBJECT),
)

_PAGINATED_PARAMS: Final[_RequestRule] = _RequestRule(
    "v2/ThreadTurnsListParams.json",
    (
        _field("v2/ThreadTurnsListParams.json", "threadId", types=_STRING, required=True),
        _field("v2/ThreadTurnsListParams.json", "cursor", types=_STRING_OR_NULL),
        _field("v2/ThreadTurnsListParams.json", "limit", types=("integer",)),
        _field(
            "v2/ThreadTurnsListParams.json",
            "sortDirection",
            types=_STRING,
            enum_contains=("asc",),
        ),
        _field(
            "v2/ThreadTurnsListParams.json",
            "itemsView",
            types=_STRING,
            enum_contains=("full",),
        ),
    ),
    ("threadId", "cursor", "limit", "sortDirection", "itemsView"),
)

_PAGINATED_FIELDS: Final[tuple[_FieldRule, ...]] = (
    _field(
        "v2/ThreadTurnsListResponse.json",
        "data",
        types=_ARRAY,
        item_types=_OBJECT,
        required=True,
    ),
    _field(
        "v2/ThreadTurnsListResponse.json",
        "nextCursor",
        types=_STRING_OR_NULL,
        required_types=_STRING_OR_NULL,
    ),
    *_TURN_FIELDS,
)

_ARCHIVE_FIELDS: Final[tuple[_FieldRule, ...]] = (
    _field("v2/ThreadArchiveParams.json", "threadId", types=_STRING, required=True),
    _field("v2/ThreadArchiveResponse.json", types=_OBJECT),
    _field(
        "v2/ThreadArchivedNotification.json",
        "threadId",
        types=_STRING,
        required=True,
    ),
)

_UNARCHIVE_FIELDS: Final[tuple[_FieldRule, ...]] = (
    _field("v2/ThreadUnarchiveParams.json", "threadId", types=_STRING, required=True),
    _field("v2/ThreadUnarchiveResponse.json", types=_OBJECT),
    _field(
        "v2/ThreadUnarchivedNotification.json",
        "threadId",
        types=_STRING,
        required=True,
    ),
)

_RULES: Final[tuple[_ContractRule, ...]] = (
    _ContractRule(
        OperationName.INVENTORY_COMMON,
        "inventory.common.v1",
        ("initialize", "thread/list", "thread/read", "thread/loaded/list"),
        request_rules=_COMMON_REQUESTS,
        document_rules=_COMMON_DOCUMENTS,
        fields=_COMMON_FIELDS + _THREAD_FIELDS + _THREAD_READ_FIELDS,
    ),
    _ContractRule(
        OperationName.HISTORY_LEGACY,
        "history.legacy.v1",
        ("thread/read",),
        request_rules=(
            _RequestRule(
                "v2/ThreadReadParams.json",
                tuple(
                    field
                    for field in _COMMON_FIELDS
                    if field.document.endswith("ThreadReadParams.json")
                ),
                ("threadId", "includeTurns"),
            ),
        ),
        document_rules=(_DocumentRule("v2/ThreadReadResponse.json", _OBJECT),),
        fields=(
            _field("v2/ThreadReadResponse.json", "thread", types=_OBJECT, required=True),
            _field(
                "v2/ThreadReadResponse.json",
                "thread",
                "turns",
                types=_ARRAY,
                item_types=_OBJECT,
                required=True,
            ),
            *_THREAD_READ_FIELDS,
            *_LEGACY_TURN_FIELDS,
        ),
    ),
    _ContractRule(
        OperationName.HISTORY_PAGINATED,
        "history.paginated.v1",
        ("thread/turns/list",),
        request_rules=(_PAGINATED_PARAMS,),
        document_rules=(_DocumentRule("v2/ThreadTurnsListResponse.json", _OBJECT),),
        fields=_PAGINATED_FIELDS,
        experimental_documents=True,
        experimental_method=True,
    ),
    _ContractRule(
        OperationName.ARCHIVE,
        "archive.v1",
        ("initialize", "thread/list", "thread/read", "thread/loaded/list", "thread/archive"),
        request_rules=(
            *_COMMON_REQUESTS,
            _RequestRule(
                "v2/ThreadArchiveParams.json",
                (_ARCHIVE_FIELDS[0],),
                ("threadId",),
            ),
        ),
        document_rules=_COMMON_DOCUMENTS,
        fields=_COMMON_FIELDS + _THREAD_FIELDS + _THREAD_READ_FIELDS + _ARCHIVE_FIELDS,
    ),
    _ContractRule(
        OperationName.UNARCHIVE,
        "unarchive.v1",
        (
            "initialize",
            "thread/list",
            "thread/read",
            "thread/loaded/list",
            "thread/unarchive",
        ),
        request_rules=(
            *_COMMON_REQUESTS,
            _RequestRule(
                "v2/ThreadUnarchiveParams.json",
                (_UNARCHIVE_FIELDS[0],),
                ("threadId",),
            ),
        ),
        document_rules=_COMMON_DOCUMENTS,
        fields=_COMMON_FIELDS + _THREAD_FIELDS + _THREAD_READ_FIELDS + _UNARCHIVE_FIELDS,
    ),
)


class _Evaluation:
    """Collect one contract's issues and its minimal runtime projection."""

    def __init__(self, documents: Mapping[str, Mapping[str, Any]]) -> None:
        self.documents = documents
        self.issues: list[ContractIssue] = []
        self._issue_keys: set[tuple[str, str, str | None, str | None]] = set()
        self.projection: list[dict[str, Any]] = []

    def issue(
        self,
        code: str,
        subject: str,
        *,
        expected: str | None = None,
        actual: Any = None,
    ) -> None:
        actual_text = None if actual is None else str(actual)
        key = (code, subject, expected, actual_text)
        if key in self._issue_keys:
            return
        self._issue_keys.add(key)
        self.issues.append(
            ContractIssue(code=code, subject=subject, expected=expected, actual=actual_text)
        )

    def document(self, name: str) -> Mapping[str, Any] | None:
        document = self.documents.get(name)
        if not isinstance(document, Mapping):
            self.issue("document_missing", name, expected="JSON object", actual=None)
            return None
        return document

    def expand(
        self, node: Any, document: Mapping[str, Any], subject: str
    ) -> list[Mapping[str, Any]]:
        if not isinstance(node, Mapping):
            return []
        reference = node.get("$ref")
        if reference is not None:
            if not isinstance(reference, str) or not reference.startswith("#/definitions/"):
                self.issue(
                    "reference_unresolved",
                    subject,
                    expected="#/definitions/<name>",
                    actual=reference,
                )
                return []
            definitions = document.get("definitions")
            name = reference.removeprefix("#/definitions/")
            target = definitions.get(name) if isinstance(definitions, Mapping) else None
            if not isinstance(target, Mapping):
                self.issue("reference_unresolved", subject, expected=reference, actual=reference)
                return []
            return self.expand(target, document, subject)
        branches: list[Mapping[str, Any]] = []
        for keyword in ("allOf", "anyOf", "oneOf"):
            values = node.get(keyword)
            if isinstance(values, list):
                branches.extend(
                    branch for value in values for branch in self.expand(value, document, subject)
                )
        if branches:
            direct = {
                key: value for key, value in node.items() if key not in {"allOf", "anyOf", "oneOf"}
            }
            if direct:
                branches.append(direct)
            return branches
        return [node]

    def project(
        self,
        nodes: list[Mapping[str, Any]],
        document: Mapping[str, Any],
        subject: str,
    ) -> _Projection:
        types: set[str] = set()
        enums: set[str] = set()
        item_types: set[str] = set()
        for node in nodes:
            raw_type = node.get("type")
            if isinstance(raw_type, str):
                types.add(raw_type)
            elif isinstance(raw_type, list):
                types.update(item for item in raw_type if isinstance(item, str))
            elif isinstance(node.get("properties"), Mapping) or isinstance(
                node.get("required"), list
            ):
                types.add("object")
            raw_enum = node.get("enum")
            if isinstance(raw_enum, list):
                enums.update(item for item in raw_enum if isinstance(item, str))
            raw_items = node.get("items")
            if isinstance(raw_items, Mapping):
                item_nodes = self.expand(raw_items, document, subject)
                item_types.update(self.project(item_nodes, document, subject).types)
        return _Projection(frozenset(types), frozenset(enums), frozenset(item_types))

    def field(self, rule: _FieldRule) -> _FieldResult:
        document = self.document(rule.document)
        if document is None:
            self.projection.append({"document": rule.document, "path": rule.path, "present": False})
            return _FieldResult(_Projection(), False, False)
        nodes: list[Mapping[str, Any]] = [document]
        required = False
        for step in rule.path:
            next_nodes: list[Mapping[str, Any]] = []
            if step == "[]":
                for parent in nodes:
                    for variant in self.expand(parent, document, f"{rule.document}#{rule.path}"):
                        raw_items = variant.get("items")
                        if isinstance(raw_items, Mapping):
                            next_nodes.extend(
                                self.expand(raw_items, document, f"{rule.document}#{rule.path}")
                            )
                nodes = next_nodes
                continue
            for parent in nodes:
                variants = self.expand(parent, document, f"{rule.document}#{rule.path}")
                for variant in variants:
                    properties = variant.get("properties")
                    if isinstance(properties, Mapping) and step in properties:
                        value = properties[step]
                        if (
                            isinstance(variant.get("required"), list)
                            and step in variant["required"]
                        ):
                            required = True
                        next_nodes.extend(
                            self.expand(value, document, f"{rule.document}#{rule.path}")
                        )
            if not next_nodes:
                self.projection.append(
                    {"document": rule.document, "path": rule.path, "present": False}
                )
                return _FieldResult(_Projection(), False, required)
            nodes = next_nodes
        result = self.project(nodes, document, f"{rule.document}#{rule.path}")
        self.projection.append(
            {
                "document": rule.document,
                "path": rule.path,
                "present": True,
                "required": required,
                "types": sorted(result.types),
                "enums": sorted(result.enums),
                "item_types": sorted(result.item_types),
            }
        )
        return _FieldResult(result, True, required)

    def required_fields(self, request: _RequestRule) -> None:
        document = self.document(request.document)
        if document is None:
            return
        known = set(request.supported_required_fields)
        for variant in self.expand(document, document, request.document):
            required = variant.get("required")
            if not isinstance(required, list):
                continue
            for name in required:
                if isinstance(name, str) and name not in known:
                    self.issue(
                        "requiredness",
                        f"{request.document}.required.{name}",
                        expected="field CSM can satisfy",
                        actual="required",
                    )


def _method_evidence(
    rule: _ContractRule,
    stable_methods: AbstractSet[str],
    experimental_methods: AbstractSet[str],
    experimental_api: bool,
    evaluation: _Evaluation,
) -> tuple[ContractMethodEvidence, ...]:
    evidence: list[ContractMethodEvidence] = []
    for method in rule.methods:
        if method in stable_methods:
            evidence.append(
                ContractMethodEvidence(method=method, stability="stable", negotiated=False)
            )
        elif method in experimental_methods and rule.experimental_method and experimental_api:
            evidence.append(
                ContractMethodEvidence(method=method, stability="experimental", negotiated=True)
            )
        elif method in experimental_methods:
            evaluation.issue(
                "method_stability",
                method,
                expected="stable",
                actual="experimental",
            )
        else:
            evaluation.issue("method_missing", method, expected="method present", actual=None)
    return tuple(evidence)


def _validate_field(evaluation: _Evaluation, rule: _FieldRule, result: _FieldResult) -> None:
    if not result.present:
        if not rule.allow_missing:
            evaluation.issue(
                "field_missing",
                f"{rule.document}#{'.'.join(rule.path)}",
                expected="field present",
                actual=None,
            )
        return
    actual_types = result.projection.types
    if rule.types and not actual_types.intersection(rule.types):
        evaluation.issue(
            "field_type",
            f"{rule.document}#{'.'.join(rule.path)}",
            expected="|".join(rule.types),
            actual="|".join(sorted(actual_types)) or None,
        )
    if rule.required_types and not set(rule.required_types).issubset(actual_types):
        evaluation.issue(
            "field_type",
            f"{rule.document}#{'.'.join(rule.path)}",
            expected="contains " + "|".join(rule.required_types),
            actual="|".join(sorted(actual_types)) or None,
        )
    actual_items = result.projection.item_types
    if rule.item_types and not actual_items.intersection(rule.item_types):
        evaluation.issue(
            "field_type",
            f"{rule.document}#{'.'.join(rule.path)}[]",
            expected="|".join(rule.item_types),
            actual="|".join(sorted(actual_items)) or None,
        )
    if rule.enum_contains and result.projection.enums:
        missing = set(rule.enum_contains) - result.projection.enums
        if missing:
            evaluation.issue(
                "enum_value",
                f"{rule.document}#{'.'.join(rule.path)}",
                expected="contains " + ",".join(rule.enum_contains),
                actual="|".join(sorted(result.projection.enums)),
            )
    if rule.required is not None and result.required is not rule.required:
        evaluation.issue(
            "requiredness",
            f"{rule.document}#{'.'.join(rule.path)}",
            expected=str(rule.required).lower(),
            actual=str(result.required).lower(),
        )


def _evaluate_rule(
    rule: _ContractRule,
    *,
    stable_documents: Mapping[str, Mapping[str, Any]],
    experimental_documents: Mapping[str, Mapping[str, Any]],
    stable_methods: AbstractSet[str],
    experimental_methods: AbstractSet[str],
    experimental_api: bool,
) -> OperationCapability:
    evaluation = _Evaluation(stable_documents)
    evidence = _method_evidence(
        rule, stable_methods, experimental_methods, experimental_api, evaluation
    )
    if rule.experimental_documents and evidence and evidence[0].stability == "experimental":
        evaluation.documents = experimental_documents
    for request in rule.request_rules:
        evaluation.required_fields(request)
        for field_rule in request.fields:
            result = evaluation.field(field_rule)
            _validate_field(evaluation, field_rule, result)
    for document_rule in rule.document_rules:
        document = evaluation.document(document_rule.document)
        if document is None:
            continue
        document_projection = evaluation.project(
            evaluation.expand(document, document, document_rule.document),
            document,
            document_rule.document,
        )
        evaluation.projection.append(
            {
                "document": document_rule.document,
                "path": (),
                "present": True,
                "types": sorted(document_projection.types),
            }
        )
        if not document_projection.types.intersection(document_rule.types):
            evaluation.issue(
                "field_type",
                document_rule.document,
                expected="|".join(document_rule.types),
                actual="|".join(sorted(document_projection.types)) or None,
            )
    groups: dict[str, bool] = {}
    for field_rule in rule.fields:
        field_result = evaluation.field(field_rule)
        if field_rule.group is not None:
            groups[field_rule.group] = groups.get(field_rule.group, False) or field_result.present
        _validate_field(evaluation, field_rule, field_result)
    for group, present in groups.items():
        if group is not None and not present:
            evaluation.issue(
                "field_missing",
                group,
                expected="one supported response shape",
                actual=None,
            )
    runtime_fingerprint = fingerprint({"methods": evidence, "projection": evaluation.projection})
    available = not evaluation.issues
    return OperationCapability(
        operation=rule.operation,
        contract_id=rule.contract_id,
        available=available,
        contract_rule_fingerprint=fingerprint(rule),
        runtime_contract_fingerprint=runtime_fingerprint,
        required_methods=rule.methods,
        method_evidence=evidence,
        issues=tuple(evaluation.issues),
    )


def evaluate_operation_contracts(
    *,
    stable_documents: Mapping[str, Mapping[str, Any]],
    experimental_documents: Mapping[str, Mapping[str, Any]],
    stable_methods: AbstractSet[str],
    experimental_methods: AbstractSet[str],
    experimental_api: bool,
) -> tuple[OperationCapability, ...]:
    """Return the five independently evaluated minimal App Server contracts."""

    return tuple(
        _evaluate_rule(
            rule,
            stable_documents=stable_documents,
            experimental_documents=experimental_documents,
            stable_methods=stable_methods,
            experimental_methods=experimental_methods,
            experimental_api=experimental_api,
        )
        for rule in _RULES
    )
