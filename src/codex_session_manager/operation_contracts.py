"""Minimal, operation-specific checks for the generated App Server schema."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from typing import Any, Final

from codex_session_manager.hashing import canonical_json_bytes, fingerprint
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
    enum_present: bool = False


@dataclass(frozen=True, slots=True)
class _SchemaShape:
    types: frozenset[str] = frozenset()
    enum: tuple[Any, ...] | None = None
    properties: tuple[tuple[str, tuple[_SchemaShape, ...]], ...] = ()
    required: frozenset[str] = frozenset()
    items: tuple[_SchemaShape, ...] | None = None
    unsatisfiable: bool = False


@dataclass(frozen=True, slots=True)
class _PathResult:
    shape: _SchemaShape | None
    required: bool = False
    declared: bool = False


def _shape_sort_key(shape: _SchemaShape) -> bytes:
    return canonical_json_bytes(shape)


def _path_result_sort_key(result: _PathResult) -> bytes:
    return canonical_json_bytes(result)


def _sorted_shapes(
    shapes: tuple[_SchemaShape, ...] | list[_SchemaShape],
) -> tuple[_SchemaShape, ...]:
    return tuple(sorted(shapes, key=_shape_sort_key))


def _sorted_enum_values(values: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(sorted(values, key=canonical_json_bytes))


def _string_enum_values(values: tuple[Any, ...] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(sorted(value for value in values if isinstance(value, str)))


@dataclass(frozen=True, slots=True)
class _FieldResult:
    projection: _Projection
    present: bool
    required: bool
    variants: tuple[_PathResult, ...] = ()


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
_SCHEMA_TYPES: Final[frozenset[str]] = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)
_MAX_SCHEMA_DEPTH: Final[int] = 64

_THREAD_FIELDS: Final[tuple[_FieldRule, ...]] = (
    _field("v2/ThreadListResponse.json", "data", "[]", "id", types=_STRING, required=True),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "createdAt",
        types=("integer", "number", "string", "null"),
        required=True,
    ),
    _field(
        "v2/ThreadListResponse.json",
        "data",
        "[]",
        "updatedAt",
        types=("integer", "number", "string", "null"),
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

    def _intersect(
        self, left: _SchemaShape, right: _SchemaShape, subject: str
    ) -> _SchemaShape | None:
        if left.unsatisfiable or right.unsatisfiable:
            return None
        if left.types and right.types:
            types = left.types & right.types
            if not types:
                return None
        else:
            types = left.types or right.types
        enum: tuple[Any, ...] | None
        if left.enum is not None and right.enum is not None:
            enum = _sorted_enum_values(tuple(value for value in left.enum if value in right.enum))
            if not enum:
                return None
        else:
            enum = left.enum if left.enum is not None else right.enum
        left_properties = dict(left.properties)
        right_properties = dict(right.properties)
        properties: list[tuple[str, tuple[_SchemaShape, ...]]] = []
        for name in sorted(left_properties.keys() | right_properties.keys()):
            if name in left_properties and name in right_properties:
                left_variants = left_properties[name]
                right_variants = right_properties[name]
                if not left_variants or not right_variants:
                    if name in left.required or name in right.required:
                        return None
                    properties.append((name, ()))
                    continue
                merged_variants = tuple(
                    merged
                    for left_variant in left_variants
                    for right_variant in right_variants
                    if (merged := self._intersect(left_variant, right_variant, subject)) is not None
                )
                if not merged_variants:
                    if name in left.required or name in right.required:
                        return None
                    # An optional property may be omitted when allOf branches
                    # impose incompatible constraints; its consumer still
                    # validates the field if the contract actually reads it.
                    properties.append((name, ()))
                    continue
                variants = _sorted_shapes(merged_variants)
            elif name in left_properties:
                variants = left_properties[name]
            else:
                variants = right_properties[name]
            properties.append((name, tuple(variants)))
        items: tuple[_SchemaShape, ...] | None
        if left.items is not None and right.items is not None:
            items = _sorted_shapes(
                tuple(
                    merged
                    for left_item in left.items
                    for right_item in right.items
                    if (merged := self._intersect(left_item, right_item, subject)) is not None
                )
            )
            if not items:
                return None
        else:
            items = left.items if left.items is not None else right.items
        return _SchemaShape(
            types=frozenset(types),
            enum=enum,
            properties=tuple(properties),
            required=left.required | right.required,
            items=items,
        )

    def _direct_shape(
        self,
        node: Mapping[str, Any],
        document: Mapping[str, Any],
        subject: str,
        ref_stack: tuple[str, ...],
        depth: int,
    ) -> _SchemaShape | None:
        raw_type = node.get("type")
        if isinstance(raw_type, str):
            if raw_type not in _SCHEMA_TYPES:
                self.issue(
                    "schema_type",
                    subject,
                    expected="JSON Schema type or non-empty type array",
                    actual=raw_type,
                )
                return None
            types = {raw_type}
        elif (
            isinstance(raw_type, list)
            and raw_type
            and all(isinstance(value, str) and value in _SCHEMA_TYPES for value in raw_type)
        ):
            types = set(raw_type)
        elif raw_type is None:
            types = set()
        else:
            self.issue(
                "schema_type",
                subject,
                expected="JSON Schema type or non-empty type array",
                actual=raw_type,
            )
            return None
        enum: tuple[Any, ...] | None = None
        if "enum" in node:
            raw_enum = node["enum"]
            if not isinstance(raw_enum, list) or not raw_enum:
                self.issue(
                    "enum_value",
                    subject,
                    expected="non-empty enum array",
                    actual=raw_enum,
                )
                return None
            enum = _sorted_enum_values(tuple(raw_enum))
        raw_required = node.get("required")
        required: frozenset[str]
        if raw_required is None:
            required = frozenset()
        elif isinstance(raw_required, list) and all(
            isinstance(value, str) for value in raw_required
        ):
            required = frozenset(raw_required)
        else:
            self.issue(
                "schema_required",
                subject,
                expected="array of field names",
                actual=raw_required,
            )
            return None
        raw_properties = node.get("properties")
        properties: list[tuple[str, tuple[_SchemaShape, ...]]] = []
        if raw_properties is not None:
            if not isinstance(raw_properties, Mapping):
                self.issue(
                    "schema_properties",
                    subject,
                    expected="JSON object",
                    actual=raw_properties,
                )
                return None
            for name, value in raw_properties.items():
                if not isinstance(name, str):
                    self.issue(
                        "schema_properties", subject, expected="string field name", actual=name
                    )
                    return None
                variants = self.expand(value, document, f"{subject}.{name}", ref_stack, depth + 1)
                if variants:
                    satisfiable = tuple(shape for shape in variants if not shape.unsatisfiable)
                    properties.append((name, _sorted_shapes(satisfiable)))
                else:
                    properties.append((name, ()))
        items: tuple[_SchemaShape, ...] | None = None
        if "items" in node:
            raw_items = node["items"]
            if not isinstance(raw_items, (Mapping, bool)):
                self.issue(
                    "schema_branch", f"{subject}.items", expected="JSON object", actual=raw_items
                )
                return None
            items = _sorted_shapes(
                self.expand(raw_items, document, f"{subject}.items", ref_stack, depth + 1)
            )
        if not types and (properties or required):
            types.add("object")
        return _SchemaShape(
            types=frozenset(types),
            enum=enum,
            properties=tuple(sorted(properties)),
            required=required,
            items=items,
        )

    def expand(
        self,
        node: Any,
        document: Mapping[str, Any],
        subject: str,
        ref_stack: tuple[str, ...] = (),
        depth: int = 0,
    ) -> list[_SchemaShape]:
        if depth > _MAX_SCHEMA_DEPTH:
            self.issue(
                "schema_depth", subject, expected=f"depth <= {_MAX_SCHEMA_DEPTH}", actual=depth
            )
            return [_SchemaShape(unsatisfiable=True)]
        if isinstance(node, bool):
            return [_SchemaShape()] if node else [_SchemaShape(unsatisfiable=True)]
        if not isinstance(node, Mapping):
            self.issue("schema_branch", subject, expected="JSON object", actual=node)
            return [_SchemaShape(unsatisfiable=True)]
        reference = node.get("$ref")
        if reference is not None:
            if not isinstance(reference, str) or not reference.startswith("#/definitions/"):
                self.issue(
                    "reference_unresolved",
                    subject,
                    expected="#/definitions/<name>",
                    actual=reference,
                )
                return [_SchemaShape(unsatisfiable=True)]
            name = reference.removeprefix("#/definitions/")
            if not name or name in ref_stack:
                self.issue(
                    "reference_cycle", subject, expected="acyclic local reference", actual=reference
                )
                return [_SchemaShape(unsatisfiable=True)]
            definitions = document.get("definitions")
            target = definitions.get(name) if isinstance(definitions, Mapping) else None
            if not isinstance(target, (Mapping, bool)):
                self.issue("reference_unresolved", subject, expected=reference, actual=reference)
                return [_SchemaShape(unsatisfiable=True)]
            resolved = self.expand(target, document, subject, (*ref_stack, name), depth + 1)
            siblings = {key: value for key, value in node.items() if key != "$ref"}
            if not siblings:
                return resolved
            local = self.expand(siblings, document, subject, ref_stack, depth + 1)
            return list(
                _sorted_shapes(
                    tuple(
                        merged
                        for resolved_shape in resolved
                        for local_shape in local
                        if (merged := self._intersect(resolved_shape, local_shape, subject))
                        is not None
                    )
                )
            ) or [_SchemaShape(unsatisfiable=True)]

        direct_node = {
            key: value for key, value in node.items() if key not in {"allOf", "anyOf", "oneOf"}
        }
        direct_shape = self._direct_shape(direct_node, document, subject, ref_stack, depth + 1)
        variants = [direct_shape] if direct_shape is not None else [
            _SchemaShape(unsatisfiable=True)
        ]
        for keyword in ("allOf", "anyOf", "oneOf"):
            if keyword not in node:
                continue
            values = node[keyword]
            if not isinstance(values, list) or not values:
                self.issue(
                    "schema_combiner",
                    subject,
                    expected=f"{keyword} non-empty array",
                    actual=values,
                )
                variants = [_SchemaShape(unsatisfiable=True)]
                continue
            if keyword == "allOf":
                combined = variants
                for index, value in enumerate(values):
                    if not isinstance(value, (Mapping, bool)):
                        self.issue(
                            "schema_branch",
                            f"{subject}.{keyword}[{index}]",
                            expected="JSON object",
                            actual=value,
                        )
                        continue
                    branch_variants = self.expand(
                        value, document, f"{subject}.{keyword}[{index}]", ref_stack, depth + 1
                    )
                    combined = [
                        merged
                        for left in combined
                        for right in branch_variants
                        if (merged := self._intersect(left, right, subject)) is not None
                    ]
                    if not combined:
                        combined = [_SchemaShape(unsatisfiable=True)]
                variants = combined
            else:
                branch_variants = []
                for index, value in enumerate(values):
                    if not isinstance(value, (Mapping, bool)):
                        self.issue(
                            "schema_branch",
                            f"{subject}.{keyword}[{index}]",
                            expected="JSON object",
                            actual=value,
                        )
                        continue
                    branch_variants.extend(
                        self.expand(
                            value,
                            document,
                            f"{subject}.{keyword}[{index}]",
                            ref_stack,
                            depth + 1,
                        )
                    )
                if not branch_variants:
                    variants = [_SchemaShape(unsatisfiable=True)]
                    continue
                variants = [
                    merged
                    for left in variants
                    for right in branch_variants
                    if (merged := self._intersect(left, right, subject)) is not None
                ]
                if not variants:
                    variants = [_SchemaShape(unsatisfiable=True)]
        return list(_sorted_shapes(variants))

    @staticmethod
    def _properties(shape: _SchemaShape) -> dict[str, tuple[_SchemaShape, ...]]:
        return dict(shape.properties)

    def _walk(self, shape: _SchemaShape, path: tuple[str, ...]) -> list[_PathResult]:
        if shape.unsatisfiable:
            return [_PathResult(None, declared=True)]
        if not path:
            return [_PathResult(shape)]
        step, *rest = path
        if step == "[]":
            if shape.items is None:
                return []
            return [result for item in shape.items for result in self._walk(item, tuple(rest))]
        children = self._properties(shape).get(step)
        if children is None:
            return []
        if not children:
            return [_PathResult(None, step in shape.required, True)]
        results: list[_PathResult] = []
        for child in children:
            child_results = self._walk(child, tuple(rest))
            if not rest:
                results.extend(
                    _PathResult(result.shape, step in shape.required, result.declared)
                    for result in child_results
                )
            else:
                results.extend(child_results)
        return results

    @staticmethod
    def _shape_item_types(shape: _SchemaShape) -> frozenset[str] | None:
        if shape.items is None:
            return None
        return frozenset(item_type for item in shape.items for item_type in item.types)

    def _projection(self, variants: tuple[_PathResult, ...]) -> _Projection:
        shapes = tuple(result.shape for result in variants if result.shape is not None)
        types = frozenset(value for shape in shapes for value in shape.types)
        enums = frozenset(
            value
            for shape in shapes
            if shape.enum is not None
            for value in shape.enum
            if isinstance(value, str)
        )
        item_types = frozenset(
            value for shape in shapes for item in (shape.items or ()) for value in item.types
        )
        return _Projection(
            types, enums, item_types, any(shape.enum is not None for shape in shapes)
        )

    def field(self, rule: _FieldRule) -> _FieldResult:
        document = self.document(rule.document)
        if document is None:
            self.projection.append({"document": rule.document, "path": rule.path, "present": False})
            return _FieldResult(_Projection(), False, False, (_PathResult(None),))
        variants: list[_PathResult] = []
        for root in self.expand(document, document, rule.document):
            found = self._walk(root, rule.path)
            variants.extend(found or [_PathResult(None)])
        result_variants = tuple(sorted(variants, key=_path_result_sort_key))
        result = self._projection(result_variants)
        self.projection.append(
            {
                "document": rule.document,
                "path": rule.path,
                "present": any(value.shape is not None for value in result_variants),
                "variants": [
                    {
                        "present": value.shape is not None,
                        "required": value.required,
                        "declared": value.declared,
                        "types": sorted(value.shape.types) if value.shape is not None else [],
                        "enums": (
                            list(_string_enum_values(value.shape.enum))
                            if value.shape is not None
                            else []
                        ),
                        "item_types": sorted(result.item_types) if value.shape is not None else [],
                    }
                    for value in result_variants
                ],
            }
        )
        return _FieldResult(
            result,
            any(value.shape is not None for value in result_variants),
            any(value.required for value in result_variants),
            result_variants,
        )

    def required_fields(self, request: _RequestRule) -> None:
        document = self.document(request.document)
        if document is None:
            return
        variants = self.expand(document, document, request.document)
        required_sets = tuple(sorted(tuple(sorted(variant.required)) for variant in variants))
        self.projection.append({"document": request.document, "required_sets": required_sets})
        known = set(request.supported_required_fields)
        if any(set(required) <= known for required in required_sets):
            return
        for name in sorted(
            {name for required in required_sets for name in required if name not in known}
        ):
            self.issue(
                "requiredness",
                f"{request.document}.required.{name}",
                expected="field CSM can satisfy",
                actual="required",
            )

    def _request_matches(self, rule: _FieldRule, result: _PathResult) -> bool:
        shape = result.shape
        if shape is None or (rule.required is True and not result.required):
            return False
        if rule.types and shape.types and not shape.types.intersection(rule.types):
            return False
        if rule.required_types and not set(rule.required_types).issubset(shape.types):
            return False
        if rule.item_types:
            if shape.types and "array" not in shape.types:
                return False
            if shape.items is not None:
                if not shape.items:
                    return False
                item_types = self._shape_item_types(shape)
                if item_types and not item_types.intersection(rule.item_types):
                    return False
        return not (
            shape.enum is not None
            and (
                not rule.enum_contains
                or not set(rule.enum_contains).intersection(
                    value for value in shape.enum if isinstance(value, str)
                )
            )
        )

    def request_satisfied(self, request: _RequestRule) -> bool:
        document = self.documents.get(request.document)
        if not isinstance(document, Mapping):
            return False
        known = set(request.supported_required_fields)
        for root in self.expand(document, document, request.document):
            if not root.required <= known:
                continue
            if all(
                any(self._request_matches(field, result) for result in self._walk(root, field.path))
                for field in request.fields
            ):
                return True
        return False


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


def _validate_field(
    evaluation: _Evaluation,
    rule: _FieldRule,
    result: _FieldResult,
    *,
    request: bool = False,
) -> None:
    subject = f"{rule.document}#{'.'.join(rule.path)}"
    if request:
        if any(evaluation._request_matches(rule, value) for value in result.variants):
            return
        if not result.present:
            evaluation.issue("field_missing", subject, expected="field present", actual=None)
        else:
            evaluation.issue(
                "schema_combiner",
                subject,
                expected="one complete request branch satisfiable by CSM",
                actual="no matching branch",
            )
        return
    if not result.present:
        if not rule.allow_missing or any(value.declared for value in result.variants):
            evaluation.issue(
                "field_missing",
                subject,
                expected="field present with satisfiable schema",
                actual=(
                    "declared but unsatisfiable"
                    if any(value.declared for value in result.variants)
                    else None
                ),
            )
        return
    if any(value.shape is None for value in result.variants) and not rule.allow_missing:
        evaluation.issue(
            "field_missing", subject, expected="field present in every response branch", actual=None
        )
    for value in result.variants:
        shape = value.shape
        if shape is None:
            continue
        actual_types = shape.types
        if rule.types and (not actual_types or not actual_types <= set(rule.types)):
            evaluation.issue(
                "field_type",
                subject,
                expected="|".join(rule.types),
                actual="|".join(sorted(actual_types)) or None,
            )
        if rule.required_types and not set(rule.required_types).issubset(actual_types):
            evaluation.issue(
                "field_type",
                subject,
                expected="contains " + "|".join(rule.required_types),
                actual="|".join(sorted(actual_types)) or None,
            )
        if rule.item_types:
            actual_items = evaluation._shape_item_types(shape)
            if actual_items is None or not actual_items or not actual_items <= set(rule.item_types):
                evaluation.issue(
                    "field_type",
                    subject + "[]",
                    expected="|".join(rule.item_types),
                    actual="|".join(sorted(actual_items or ())) or None,
                )
        if rule.required is not None and value.required is not rule.required:
            evaluation.issue(
                "requiredness",
                subject,
                expected=str(rule.required).lower(),
                actual=str(value.required).lower(),
            )
    if rule.enum_contains:
        for value in result.variants:
            shape = value.shape
            if shape is None:
                continue
            if shape.enum is None:
                evaluation.issue(
                    "enum_value",
                    subject,
                    expected="contains " + ",".join(rule.enum_contains),
                    actual=None,
                )
                continue
            if not set(rule.enum_contains).intersection(_string_enum_values(shape.enum)):
                evaluation.issue(
                    "enum_value",
                    subject,
                    expected="contains " + ",".join(rule.enum_contains),
                    actual="|".join(_string_enum_values(shape.enum)) or None,
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
            _validate_field(evaluation, field_rule, result, request=True)
        if not evaluation.request_satisfied(request):
            evaluation.issue(
                "schema_combiner",
                request.document,
                expected="one complete request branch satisfiable by CSM",
                actual="no matching branch",
            )
    request_fields = {field_rule for request in rule.request_rules for field_rule in request.fields}
    for document_rule in rule.document_rules:
        document = evaluation.document(document_rule.document)
        if document is None:
            continue
        document_shapes = _sorted_shapes(
            evaluation.expand(document, document, document_rule.document)
        )
        for shape in document_shapes:
            document_projection = evaluation._projection((_PathResult(shape),))
            evaluation.projection.append(
                {
                    "document": document_rule.document,
                    "path": (),
                    "present": True,
                    "types": sorted(document_projection.types),
                }
            )
            if not document_projection.types or not document_projection.types <= set(
                document_rule.types
            ):
                evaluation.issue(
                    "field_type",
                    document_rule.document,
                    expected="|".join(document_rule.types),
                    actual="|".join(sorted(document_projection.types)) or None,
                )
        if not document_shapes:
            evaluation.issue(
                "schema_combiner",
                document_rule.document,
                expected="satisfiable schema",
                actual=None,
            )
    groups: dict[str, bool] = {}
    for field_rule in rule.fields:
        if field_rule in request_fields:
            continue
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
