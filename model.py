"""
Conditional Pydantic Schema Library with Dynamic Templates.

The public compatibility entry point is ``main``; this module contains the
implementation used by the focused compatibility modules.
"""

from __future__ import annotations

import copy
import itertools
import json
from enum import Enum
from typing import (
    Any,
    Dict,
    FrozenSet,
    Iterator,
    List,
    Literal,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    Union,
    get_args,
    get_origin,
    overload,
)

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

import conditions as _conditions
import records as _records
import schema as _schema
import templates as _templates

AnyOf = _conditions.AnyOf
CSYesNo = _conditions.CSYesNo
FALSY = _conditions.FALSY
NoneOf = _conditions.NoneOf
TRUTHY = _conditions.TRUTHY
UNBOUND = _conditions.UNBOUND
_MISSING = _conditions._MISSING
any_of = _conditions.any_of
none_of = _conditions.none_of
truthy = _conditions.truthy
CSRecord = _records.CSRecord
CSRecordTemplate = _records.CSRecordTemplate
CSrecord = _records.CSrecord
_build_compact_schema = _schema._build_compact_schema
_build_conditional_schema = _schema._build_conditional_schema
_cache_schema_result = _schema._cache_schema_result
_common_schema_properties = _schema._common_schema_properties
_condition_set_schema = _schema._condition_set_schema
_condition_value_schema = _schema._condition_value_schema
_conditional_schema_predicate = _schema._conditional_schema_predicate
_merge_variant_schema_definitions = _schema._merge_variant_schema_definitions
_replace_schema_refs = _schema._replace_schema_refs
_schema_fingerprint = _schema._schema_fingerprint
_schema_property_name = _schema._schema_property_name
_strip_descriptions = _schema._strip_descriptions
CStemplate = _templates.CStemplate
CSliteral = _templates.CSliteral
LiteralTemplate = _templates.LiteralTemplate
Template = _templates.Template
_has_implicit_literal_template = _templates._has_implicit_literal_template
_resolve_implicit_literal_template = _templates._resolve_implicit_literal_template

_GENERATED_CLASS_MARKER = "__conditional_generated__"
_VARIANT_CLASS_MARKER = "__conditional_variant__"
_DYNAMIC_RECORD_MARKER = "__conditional_dynamic_record__"
_MAX_VARIANTS_FOR_UNION = 256
_BOUND_CACHE_LIMIT = 64
_NESTED_MODEL_CACHE_LIMIT = 256
_NESTED_MODEL_CACHE: Dict[Any, FrozenSet[Type[BaseModel]]] = {}


def _variant_name_suffix(active_combo: Dict[str, Any]) -> str:
    """Build a readable, typed, and identifier-safe variant name suffix."""
    if not active_combo:
        return "default"
    parts = []
    for field_name, value in active_combo.items():
        rendered = repr(value)
        safe_value = "".join(character if character.isalnum() else "_" for character in rendered).strip("_")
        parts.append(f"{field_name}_{type(value).__name__}_{safe_value or 'value'}")
    return "_".join(parts)


class ConditionalFieldInfo:
    """Store the field type, runtime predicates, bind-time predicates, and metadata."""

    __slots__ = (
        "field_type",
        "when",
        "when_any",
        "when_bound",
        "when_truthy",
        "when_falsy",
        "when_unbound",
        "default",
        "alias",
        "description",
        "pattern",
        "enum",
        "field_kwargs",
        "bound_active_result",
        "_dependency_fields_cache",
    )

    def __init__(
        self,
        field_type: Union[Type[Any], LiteralTemplate, CSRecordTemplate, None] = None,
        when: Optional[Dict[str, Any]] = None,
        when_any: Optional[List[Dict[str, Any]]] = None,
        when_bound: Optional[Union[Dict[str, Any], List[str]]] = None,
        when_truthy: Optional[List[str]] = None,
        when_falsy: Optional[List[str]] = None,
        when_unbound: Optional[List[str]] = None,
        default: Any = ...,
        alias: Optional[str] = None,
        description: Optional[Union[str, Template]] = None,
        pattern: Optional[Union[str, Template]] = None,
        enum: Optional[Union[List, Template]] = None,
        **field_kwargs: Any,
    ):
        self.field_type = field_type
        self.when = when or {}
        self.when_any = when_any
        self.default = default
        self.alias = alias
        self.description = description
        self.pattern = pattern
        self.enum = enum
        self.field_kwargs = field_kwargs
        self.bound_active_result = True
        self._dependency_fields_cache: Optional[FrozenSet[str]] = None

        # Initialize condition lists
        self.when_truthy: List[str] = list(when_truthy) if when_truthy else []
        self.when_falsy: List[str] = list(when_falsy) if when_falsy else []
        self.when_unbound: List[str] = list(when_unbound) if when_unbound else []

        # Process when_bound - support both dict and list formats
        self.when_bound: Dict[str, Any] = {}

        if when_bound is not None:
            if isinstance(when_bound, (list, tuple)):
                # List format: treat each item as a truthy check
                self.when_truthy.extend(when_bound)
            elif isinstance(when_bound, dict):
                self.when_bound = dict(when_bound)
            else:
                raise TypeError(f"when_bound must be a dict or list, got {type(when_bound).__name__}")

    @property
    def dependency_fields(self) -> FrozenSet[str]:
        """Get the set of field names this field depends on (for runtime conditions)."""
        if self._dependency_fields_cache is None:
            deps: Set[str] = set(self.when.keys())
            if self.when_any:
                for cond_set in self.when_any:
                    deps.update(cond_set.keys())
            self._dependency_fields_cache = frozenset(deps)
        return self._dependency_fields_cache

    def evaluate(self, combo: Dict[str, Any]) -> bool:
        """Evaluate if the field should be active for a given combination of control values."""
        # Check 'when' conditions (all must match)
        for field_name, condition in self.when.items():
            if field_name not in combo:
                return False
            actual = combo[field_name]
            if isinstance(condition, AnyOf):
                if not condition.evaluate(actual):
                    return False
            elif isinstance(condition, NoneOf):
                if not condition.evaluate(actual):
                    return False
            elif actual != condition:
                return False

        # Check 'when_any' conditions (at least one set must match)
        if self.when_any:
            any_matched = False
            for condition_set in self.when_any:
                all_in_set_match = True
                for field_name, condition in condition_set.items():
                    if field_name not in combo:
                        all_in_set_match = False
                        break
                    actual = combo[field_name]
                    if isinstance(condition, AnyOf):
                        if not condition.evaluate(actual):
                            all_in_set_match = False
                            break
                    elif isinstance(condition, NoneOf):
                        if not condition.evaluate(actual):
                            all_in_set_match = False
                            break
                    elif actual != condition:
                        all_in_set_match = False
                        break
                if all_in_set_match:
                    any_matched = True
                    break
            if not any_matched:
                return False

        return True

    def evaluate_bound(self, ctx: Dict[str, Any]) -> bool:
        """Evaluate bind-time conditions."""
        # Check unbound conditions (keys must NOT be in context)
        for key in self.when_unbound:
            if not UNBOUND.check(ctx, key):
                return False

        # Check truthy conditions
        for key in self.when_truthy:
            value = ctx.get(key, _MISSING)
            if value is _MISSING or not truthy(value):
                return False

        # Check falsy conditions
        for key in self.when_falsy:
            value = ctx.get(key, _MISSING)
            if value is _MISSING or truthy(value):
                return False

        # Check dict-based conditions
        for key, condition in self.when_bound.items():
            if condition is UNBOUND:
                if not UNBOUND.check(ctx, key):
                    return False
                continue

            actual = ctx.get(key, _MISSING)
            if actual is _MISSING:
                return False
            if isinstance(condition, AnyOf):
                if not condition.evaluate(actual):
                    return False
            elif isinstance(condition, NoneOf):
                if not condition.evaluate(actual):
                    return False
            elif callable(condition):
                if not condition(actual):
                    return False
            elif actual != condition:
                return False

        return True

    @property
    def requires_bind(self) -> bool:
        """Check if this field requires bind() to be called."""
        return bool(
            self.when_truthy
            or self.when_falsy
            or self.when_unbound
            or self.when_bound
            or isinstance(self.field_type, LiteralTemplate)
            or isinstance(self.field_type, CSRecordTemplate)
            or isinstance(self.pattern, Template)
            or isinstance(self.enum, Template)
            or isinstance(self.description, Template)
            or isinstance(self.alias, Template)
            or (
                get_origin(self.field_type) is Literal
                and any(isinstance(a, str) and _has_implicit_literal_template(a) for a in get_args(self.field_type))
            )
        )

    def resolve_templates(self, ctx: Dict[str, Any]) -> "ConditionalFieldInfo":
        """Resolve all template values with the given context."""

        def resolve(val: Any) -> Any:
            if isinstance(val, Template):
                return val.resolve(ctx)
            return val

        # Resolve field type
        resolved_type = self.field_type

        if isinstance(self.field_type, LiteralTemplate):
            # Resolve LiteralTemplate to actual Literal type
            resolved_type = self.field_type.resolve(ctx)
        elif isinstance(self.field_type, CSRecordTemplate):
            # Resolve CSRecordTemplate to a dynamically generated model
            resolved_type = self.field_type.resolve(ctx)
        elif get_origin(self.field_type) is Literal:
            # Resolve string templates in Literal args
            args = get_args(self.field_type)
            new_args = []
            for arg in args:
                if isinstance(arg, str):
                    new_args.append(_resolve_implicit_literal_template(arg, ctx))
                else:
                    new_args.append(arg)
            resolved_type = Literal[tuple(new_args)]

        bound_active = self.evaluate_bound(ctx)

        result = ConditionalFieldInfo(
            field_type=resolved_type,
            when=self.when,
            when_any=self.when_any,
            when_bound={},  # Already evaluated
            when_truthy=[],  # Already evaluated
            when_falsy=[],  # Already evaluated
            when_unbound=[],  # Already evaluated
            default=self.default,
            alias=resolve(self.alias),
            description=resolve(self.description),
            pattern=resolve(self.pattern),
            enum=resolve(self.enum),
            **self.field_kwargs,
        )
        result.bound_active_result = bound_active
        return result

    def make_field_info(self) -> Tuple[Type, FieldInfo]:
        """Create Pydantic field info for an active field."""
        extra = dict(self.field_kwargs)
        field_type = self.field_type

        if self.pattern:
            extra["pattern"] = self.pattern
        if self.enum is not None:
            if not self.enum:
                raise ValueError("enum must contain at least one value")
            field_type = Literal[tuple(self.enum)]

        return (
            field_type,
            Field(
                default=self.default,
                alias=self.alias,
                description=self.description,
                **extra,
            ),
        )


class _ConditionIndex:
    """Immutable condition metadata shared by variant generation paths."""

    __slots__ = ("control_fields", "dependents", "dependency_order", "condition_values")

    def __init__(
        self,
        control_fields: Sequence[str],
        dependents: Dict[str, Sequence[str]],
        dependency_order: Sequence[str],
        condition_values: Dict[str, Sequence[Any]],
    ):
        self.control_fields = tuple(control_fields)
        self.dependents = {name: tuple(values) for name, values in dependents.items()}
        self.dependency_order = tuple(dependency_order)
        self.condition_values = {name: tuple(values) for name, values in condition_values.items()}


def _bind_context_cache_key(
    conditional_fields: Dict[str, ConditionalFieldInfo], ctx: Dict[str, Any]
) -> Optional[Tuple[Tuple[str, Type[Any], Any], ...]]:
    """Return a safe cache key for deterministic, hashable bind operations."""
    for cond_info in conditional_fields.values():
        dynamic_values = (
            cond_info.field_type,
            cond_info.pattern,
            cond_info.enum,
            cond_info.description,
            cond_info.alias,
        )
        if any(
            (isinstance(value, Template) and callable(value.value))
            or (isinstance(value, LiteralTemplate) and callable(value.condition))
            or (callable(value) and not isinstance(value, type))
            for value in dynamic_values
        ):
            return None
        if any(callable(value) for value in cond_info.when_bound.values()):
            return None

    try:
        key = tuple(sorted(((name, type(value), value) for name, value in ctx.items()), key=lambda item: item[0]))
        hash(key)
    except TypeError:
        return None
    return key


@overload
def CSField(
    field_type: Union[Type[Any], LiteralTemplate, CSRecordTemplate, None],
    *,
    when: Optional[Dict[str, Any]] = None,
    when_any: Optional[List[Dict[str, Any]]] = None,
    when_bound: Optional[Union[Dict[str, Any], List[str]]] = None,
    when_truthy: Optional[List[str]] = None,
    when_falsy: Optional[List[str]] = None,
    when_unbound: Optional[List[str]] = None,
    default: Any = ...,
    alias: Optional[str] = None,
    description: Optional[Union[str, Template]] = None,
    pattern: Optional[Union[str, Template]] = None,
    enum: Optional[Union[List, Template]] = None,
    **field_kwargs: Any,
) -> Any: ...


@overload
def CSField(
    *,
    when: Optional[Dict[str, Any]] = None,
    when_any: Optional[List[Dict[str, Any]]] = None,
    when_bound: Optional[Union[Dict[str, Any], List[str]]] = None,
    when_truthy: Optional[List[str]] = None,
    when_falsy: Optional[List[str]] = None,
    when_unbound: Optional[List[str]] = None,
    default: Any = ...,
    alias: Optional[str] = None,
    description: Optional[Union[str, Template]] = None,
    pattern: Optional[Union[str, Template]] = None,
    enum: Optional[Union[List, Template]] = None,
    **field_kwargs: Any,
) -> Any: ...


def CSField(
    field_type: Union[Type[Any], LiteralTemplate, CSRecordTemplate, None] = None,
    *,
    when: Optional[Dict[str, Any]] = None,
    when_any: Optional[List[Dict[str, Any]]] = None,
    when_bound: Optional[Union[Dict[str, Any], List[str]]] = None,
    when_truthy: Optional[List[str]] = None,
    when_falsy: Optional[List[str]] = None,
    when_unbound: Optional[List[str]] = None,
    default: Any = ...,
    alias: Optional[str] = None,
    description: Optional[Union[str, Template]] = None,
    pattern: Optional[Union[str, Template]] = None,
    enum: Optional[Union[List, Template]] = None,
    **field_kwargs: Any,
) -> Any:
    """Declare a conditional Pydantic field.

    Args:
        field_type: Type, ``LiteralTemplate``, ``CSRecordTemplate``, or ``None``
            to infer the type from the annotation.
        when: Runtime field-name conditions; every entry must match.
        when_any: Runtime field-name condition sets; at least one must match.
        when_bound: Bind-time value/callable mapping or truthy context keys.
        when_truthy: Context keys that must be present and truthy.
        when_falsy: Context keys that must be present and falsy.
        when_unbound: Context keys that must be absent.
        default: Value used when the field is active.
        alias: Schema property alias; conditions always use field names.
        description: Static or explicit ``CStemplate`` description.
        pattern: Static or explicit ``CStemplate`` regex pattern.
        enum: Values enforced as a Literal and emitted in the schema.
        **field_kwargs: Additional Pydantic ``Field`` arguments.

    Returns:
        A ``ConditionalFieldInfo`` descriptor consumed by ``ConditionalModel``.

    Raises:
        TypeError: If ``when_bound`` is neither a mapping nor a list.
        ValueError: If ``enum`` is empty when a model field is generated.
    """
    # Treat Ellipsis as None (infer from annotation)
    if field_type is ...:
        field_type = None

    return ConditionalFieldInfo(
        field_type=field_type,
        when=when,
        when_any=when_any,
        when_bound=when_bound,
        when_truthy=when_truthy,
        when_falsy=when_falsy,
        when_unbound=when_unbound,
        default=default,
        alias=alias,
        description=description,
        pattern=pattern,
        enum=enum,
        **field_kwargs,
    )


def _get_control_values(
    control_fields: Sequence[str],
    annotations: Dict[str, Type],
    bind_ctx: Optional[Dict[str, Any]] = None,
    conditional_fields: Optional[Dict[str, ConditionalFieldInfo]] = None,
) -> Dict[str, Tuple[Any, ...]]:
    """Return the finite values available for each runtime controller."""
    control_values: Dict[str, Tuple[Any, ...]] = {}

    for cf_name in control_fields:
        if cf_name not in annotations:
            raise ValueError(f"Unknown conditional controller field: {cf_name!r}")

        cond_info = conditional_fields.get(cf_name) if conditional_fields is not None else None
        if cond_info is not None and cond_info.enum is not None and not isinstance(cond_info.enum, Template):
            values = tuple(cond_info.enum)
        else:
            ann = cond_info.field_type if cond_info is not None else annotations[cf_name]
            if ann is None:
                ann = annotations[cf_name]
            origin = get_origin(ann)
            if origin is Literal:
                values = get_args(ann)
            elif isinstance(ann, type) and issubclass(ann, Enum):
                values = tuple(ann)
            elif ann is bool:
                values = (True, False)
            else:
                raise ValueError(
                    f"Conditional controller {cf_name!r} must use a finite Literal, Enum, or bool annotation; got {ann!r}"
                )

        if not values:
            raise ValueError(f"Conditional controller {cf_name!r} has no possible values")
        control_values[cf_name] = tuple(values)

    return control_values


def _generate_combos(
    control_fields: Sequence[str],
    control_values: Dict[str, Tuple[Any, ...]],
) -> Iterator[Dict[str, Any]]:
    """Generate all combinations of control field values using itertools.product."""
    if not control_fields:
        yield {}
        return

    value_lists = [control_values.get(f, (None,)) for f in control_fields]
    for values in itertools.product(*value_lists):
        yield dict(zip(control_fields, values))


def _narrow_controller_field(field_info: FieldInfo, value: Any) -> Tuple[Any, FieldInfo]:
    """Constrain a controller and remove defaults that do not match it."""
    narrowed_info = copy.deepcopy(field_info)
    default = narrowed_info.default
    if (default is not PydanticUndefined and default != value) or narrowed_info.default_factory is not None:
        narrowed_info.default = PydanticUndefined
        narrowed_info.default_factory = None
    return Literal[value], narrowed_info


class ConditionalModelMeta(type(BaseModel)):
    """Metaclass for ConditionalModel that handles variant generation."""

    def __new__(mcs, name: str, bases: Tuple[type, ...], namespace: Dict[str, Any], **kwargs):
        generated = namespace.pop(_GENERATED_CLASS_MARKER, False) or kwargs.pop(_GENERATED_CLASS_MARKER, False)
        if generated:
            return super().__new__(mcs, name, bases, namespace, **kwargs)

        # The exported base class inherits directly from BaseModel. Every user
        # model inherits from a ConditionalModel subclass and should be processed,
        # regardless of its name.
        if not any(isinstance(base, ConditionalModelMeta) for base in bases):
            return super().__new__(mcs, name, bases, namespace, **kwargs)

        inherited_cfields: Dict[str, ConditionalFieldInfo] = {}
        inherited_annotations: Dict[str, Any] = {}
        for base in bases:
            inherited_annotations.update(getattr(base, "__annots__", {}))
            for field_name, field_info in getattr(base, "__cfields__", {}).items():
                inherited_cfields[field_name] = copy.deepcopy(field_info)

        current_annotations = namespace.get("__annotations__")
        if current_annotations is None:
            annotate = namespace.get("__annotate_func__")
            current_annotations = annotate(1) if annotate is not None else {}
        raw_annotations = dict(inherited_annotations)
        raw_annotations.update(current_annotations)
        conditional_fields = inherited_cfields

        # Separate conditional fields from regular fields
        for field_name, field_value in list(namespace.items()):
            if isinstance(field_value, ConditionalFieldInfo):
                if field_value.field_type is None:
                    field_value.field_type = raw_annotations.get(field_name, Any)
                conditional_fields[field_name] = field_value

                # Conditional fields are optional placeholders on the base class. The
                # generated variants restore the real default and requiredness.
                extra = dict(field_value.field_kwargs)
                if field_value.pattern is not None and not isinstance(field_value.pattern, Template):
                    extra["pattern"] = field_value.pattern
                namespace[field_name] = Field(
                    default=(
                        field_value.default
                        if not field_value.when and not field_value.when_any and not field_value.requires_bind
                        else None
                    ),
                    alias=field_value.alias if isinstance(field_value.alias, str) else None,
                    description=field_value.description if not isinstance(field_value.description, Template) else None,
                    **extra,
                )

        cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        # Pydantic has now resolved postponed annotations and inherited fields.
        annotations = {field_name: field_info.annotation for field_name, field_info in cls.model_fields.items()}
        for field_name, cond_info in conditional_fields.items():
            if field_name not in cls.model_fields:
                raise TypeError(f"Conditional field {field_name!r} was not registered by Pydantic")
            if isinstance(cond_info.field_type, str) or cond_info.field_type is None:
                cond_info.field_type = cls.model_fields[field_name].annotation

        regular_fields: Dict[str, Tuple[Type, Any]] = {
            field_name: (field_info.annotation, field_info)
            for field_name, field_info in cls.model_fields.items()
            if field_name not in conditional_fields
        }

        # Build alias metadata and reject ambiguous names before validating conditions.
        alias_to_field: Dict[str, str] = {}
        field_names = set(annotations)
        for field_name, (_, field_value) in regular_fields.items():
            if isinstance(field_value, FieldInfo) and field_value.alias:
                if field_value.alias in field_names and field_value.alias != field_name:
                    raise ValueError(f"Field alias {field_value.alias!r} is an ambiguous alias for {field_name!r}")
                if field_value.alias in alias_to_field and alias_to_field[field_value.alias] != field_name:
                    raise ValueError(f"Field alias {field_value.alias!r} is an ambiguous alias")
                alias_to_field[field_value.alias] = field_name
        for field_name, cond_info in conditional_fields.items():
            if isinstance(cond_info.alias, str):
                if cond_info.alias in field_names and cond_info.alias != field_name:
                    raise ValueError(f"Field alias {cond_info.alias!r} is an ambiguous alias for {field_name!r}")
                if cond_info.alias in alias_to_field and alias_to_field[cond_info.alias] != field_name:
                    raise ValueError(f"Field alias {cond_info.alias!r} is an ambiguous alias")
                alias_to_field[cond_info.alias] = field_name

        mcs._validate_condition_names(conditional_fields, field_names, alias_to_field)

        condition_index = mcs._build_condition_index(conditional_fields, annotations)

        # Check if binding is required
        needs_bind = any(cf.requires_bind for cf in conditional_fields.values())

        # Validate controller annotations without materializing their combinations.
        if not needs_bind:
            control_fields = condition_index.control_fields
            _get_control_values(control_fields, annotations, conditional_fields=conditional_fields)
            variants = None
        else:
            variants = []

        # Attach metadata
        type.__setattr__(cls, "__cfields__", conditional_fields)
        type.__setattr__(cls, "__rfields__", regular_fields)
        type.__setattr__(cls, "__annots__", annotations)
        type.__setattr__(cls, "__needs_bind__", needs_bind)
        type.__setattr__(cls, "__variants__", variants)
        type.__setattr__(cls, "__condition_index__", condition_index)
        type.__setattr__(cls, "__active_fields__", None)

        return cls

    @staticmethod
    def _get_control_fields(conditional_fields: Dict[str, ConditionalFieldInfo], annotations: Dict[str, Any]) -> List[str]:
        """Return runtime controllers in declaration order."""
        return list(ConditionalModelMeta._build_condition_index(conditional_fields, annotations).control_fields)

    @staticmethod
    def _build_condition_index(
        conditional_fields: Dict[str, ConditionalFieldInfo], annotations: Dict[str, Any]
    ) -> _ConditionIndex:
        """Index condition dependencies, condition values, and evaluation order once."""
        field_names = set(annotations)
        conditional_names = set(conditional_fields)
        controller_names: Set[str] = set()
        dependents: Dict[str, List[str]] = {}
        condition_values: Dict[str, List[Any]] = {}
        graph: Dict[str, Set[str]] = {}

        for field_name, cond_info in conditional_fields.items():
            graph[field_name] = set()
            condition_sets = []
            if cond_info.when:
                condition_sets.append(cond_info.when)
            if cond_info.when_any:
                condition_sets.extend(cond_info.when_any)

            for condition_set in condition_sets:
                for dependency, condition in condition_set.items():
                    if dependency not in field_names:
                        raise ValueError(f"Conditional field {field_name!r} has unknown conditional dependency: {dependency}")
                    controller_names.add(dependency)
                    dependency_dependents = dependents.setdefault(dependency, [])
                    if field_name not in dependency_dependents:
                        dependency_dependents.append(field_name)
                    graph[field_name].add(dependency)
                    values = condition.get_values() if isinstance(condition, (AnyOf, NoneOf)) else (condition,)
                    condition_values.setdefault(dependency, []).extend(values)

        visiting: Set[str] = set()
        visited: Set[str] = set()
        dependency_order: List[str] = []

        def visit(field_name: str, path: Tuple[str, ...] = ()) -> None:
            if field_name in visiting:
                cycle_start = path.index(field_name) if field_name in path else 0
                cycle = " -> ".join((*path[cycle_start:], field_name))
                raise ValueError(f"cyclic conditional dependency: {cycle}")
            if field_name in visited:
                return
            visiting.add(field_name)
            for dependency in graph.get(field_name, set()):
                if dependency in conditional_names:
                    visit(dependency, (*path, field_name))
            visiting.remove(field_name)
            visited.add(field_name)
            if field_name in conditional_names:
                dependency_order.append(field_name)

        for field_name in conditional_fields:
            visit(field_name)

        control_fields = [field_name for field_name in annotations if field_name in controller_names]
        return _ConditionIndex(control_fields, dependents, dependency_order, condition_values)

    @staticmethod
    def _validate_condition_names(
        conditional_fields: Dict[str, ConditionalFieldInfo],
        field_names: Set[str],
        alias_to_field: Dict[str, str],
    ) -> None:
        """Require runtime conditions to use canonical Python field names."""
        for field_name, cond_info in conditional_fields.items():
            condition_sets = []
            if cond_info.when:
                condition_sets.append(cond_info.when)
            if cond_info.when_any:
                condition_sets.extend(cond_info.when_any)
            for condition_set in condition_sets:
                for dependency in condition_set:
                    if dependency in alias_to_field and dependency not in field_names:
                        target = alias_to_field[dependency]
                        raise ValueError(
                            f"Conditional field {field_name!r} must use field name {target!r}, not alias {dependency!r}"
                        )

    @staticmethod
    def _validate_dependencies(conditional_fields: Dict[str, ConditionalFieldInfo], annotations: Dict[str, Any]) -> None:
        """Reject missing runtime dependencies and cycles before variant generation."""
        ConditionalModelMeta._build_condition_index(conditional_fields, annotations)

    @staticmethod
    def _generate_variants(
        name: str,
        regular_fields: Dict[str, Tuple[Type, Any]],
        conditional_fields: Dict[str, ConditionalFieldInfo],
        annotations: Dict[str, Type],
        bind_ctx: Optional[Dict[str, Any]] = None,
        base_model: Optional[Type[BaseModel]] = None,
        condition_index: Optional[_ConditionIndex] = None,
    ) -> List[Type[BaseModel]]:
        """Generate all variant models based on control field combinations."""

        # Keep controller order tied to the model declaration order. Bind context
        # values are intentionally separate from runtime controller input.
        condition_index = condition_index or ConditionalModelMeta._build_condition_index(conditional_fields, annotations)
        control_fields = list(condition_index.control_fields)
        control_fields = [
            field_name
            for field_name in control_fields
            if field_name not in conditional_fields or conditional_fields[field_name].bound_active_result
        ]

        # Get possible values for each controller.
        control_values = _get_control_values(
            control_fields,
            annotations,
            bind_ctx,
            conditional_fields=conditional_fields,
        )

        # Generate all combinations
        combos = _generate_combos(control_fields, control_values)

        variants = []
        seen_signatures: Set[Tuple[Any, ...]] = set()

        for combo in combos:
            variant_fields: Dict[str, Tuple[Type, Any]] = {}
            active_conditional_fields: Set[str] = set()

            available_values = {
                field_name: value for field_name, value in combo.items() if field_name not in conditional_fields
            }
            for field_name in condition_index.dependency_order:
                cond_info = conditional_fields[field_name]
                if not cond_info.bound_active_result:
                    continue
                if cond_info.evaluate(available_values):
                    active_conditional_fields.add(field_name)
                    if field_name in combo:
                        available_values[field_name] = combo[field_name]

            # Evaluate each conditional field
            conditional_field_values: Dict[str, Tuple[Type, Any]] = {}
            for field_name in annotations:
                if field_name not in active_conditional_fields:
                    continue
                cond_info = conditional_fields[field_name]
                ftype, finfo = cond_info.make_field_info()
                conditional_field_values[field_name] = (ftype, finfo)

            # Fix control field values in this variant
            control_field_overrides: Dict[str, Tuple[Type, Any]] = {}
            for cf_name, cf_val in combo.items():
                is_active_cf = (
                    cf_name in regular_fields or cf_name in active_conditional_fields or cf_name not in conditional_fields
                )
                if not is_active_cf:
                    continue

                if cf_name in annotations:
                    if cf_name in regular_fields:
                        _, original_field = regular_fields[cf_name]
                        if isinstance(original_field, FieldInfo):
                            control_field_overrides[cf_name] = _narrow_controller_field(original_field, cf_val)
                            continue
                    elif cf_name in conditional_fields:
                        cond_field = conditional_fields[cf_name]
                        _, original_field = cond_field.make_field_info()
                        control_field_overrides[cf_name] = _narrow_controller_field(original_field, cf_val)

            # Build variant_fields in original annotation order
            for field_name in annotations.keys():
                if field_name in control_field_overrides:
                    variant_fields[field_name] = control_field_overrides[field_name]
                elif field_name in conditional_field_values:
                    variant_fields[field_name] = conditional_field_values[field_name]
                elif field_name in regular_fields:
                    variant_fields[field_name] = regular_fields[field_name]

            # Create signature to deduplicate equivalent variants
            active_controller_values = tuple(
                (field_name, type(combo[field_name]), combo[field_name])
                for field_name in control_fields
                if field_name in control_field_overrides
            )
            active_field_bits = 0
            for field_index, field_name in enumerate(annotations):
                if field_name in active_conditional_fields:
                    active_field_bits |= 1 << field_index
            signature = (
                active_controller_values,
                active_field_bits,
            )

            # Skip duplicate variants
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            active_combo = {field_name: combo[field_name] for field_name, _, _ in active_controller_values}
            suffix = _variant_name_suffix(active_combo)

            variant = create_model(
                f"{name}_{suffix}",
                __base__=base_model or BaseModel,
                __cls_kwargs__={_GENERATED_CLASS_MARKER: True},
                **variant_fields,
            )
            expected_fields = set(variant_fields)
            for field_name in list(variant.model_fields):
                if field_name not in expected_fields:
                    del variant.model_fields[field_name]
            config = dict(getattr(base_model, "model_config", {}))
            config["extra"] = "forbid"
            variant.model_config = ConfigDict(**config)
            type.__setattr__(variant, _VARIANT_CLASS_MARKER, True)
            variant.model_rebuild(force=True)
            variants.append(variant)

        return variants


class ConditionalModel(BaseModel, metaclass=ConditionalModelMeta):
    """Base class for models whose fields can be conditional at runtime or bind time."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="after")
    def _validate_conditional_shape(self) -> "ConditionalModel":
        """Ensure direct model validation accepts one generated variant shape."""
        model_type = type(self)
        if getattr(model_type, _VARIANT_CLASS_MARKER, False):
            return self

        variants = model_type._get_variants() if hasattr(model_type, "_get_variants") else ()
        if not variants:
            return self

        data = {
            field_name: getattr(self, field_name)
            for field_name in self.model_fields_set
            if field_name in model_type.model_fields
        }
        for variant in variants:
            try:
                validated = variant.model_validate(data)
                for field_name in variant.model_fields:
                    if field_name not in self.model_fields_set:
                        object.__setattr__(self, field_name, getattr(validated, field_name))
                object.__setattr__(self, "_conditional_active_fields", frozenset(variant.model_fields))
                return self
            except Exception:
                continue

        raise ValueError("Input does not match any conditional model variant")

    def model_dump(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Dump only the fields active in the matched conditional variant."""
        result = super().model_dump(*args, **kwargs)
        active_fields = getattr(self, "_conditional_active_fields", None)
        if active_fields is None:
            return result

        by_alias = kwargs.get("by_alias")
        if by_alias is None:
            by_alias = self.model_config.get("serialize_by_alias", False)
        output_names = {
            (field_info.serialization_alias or field_info.alias or field_name) if by_alias else field_name
            for field_name, field_info in type(self).model_fields.items()
            if field_name not in active_fields
        }
        return {key: value for key, value in result.items() if key not in output_names}

    def model_dump_json(self, **kwargs: Any) -> str:
        """Serialize the same active shape as :meth:`model_dump`."""
        indent = kwargs.pop("indent", None)
        ensure_ascii = kwargs.pop("ensure_ascii", False)
        data = self.model_dump(mode="json", **kwargs)
        return json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, separators=None if indent else (",", ":"))

    @classmethod
    def bind(cls, **ctx: Any) -> Type["ConditionalModel"]:
        """Resolve bind-time conditions and return a bound model subclass.

        Args:
            **ctx: Context values used by templates, records, and bind-time predicates.

        Returns:
            A model subclass containing only fields active for ``ctx``.

        Raises:
            ValueError: If a template, conditional Literal, or record cannot be resolved.
            TypeError: If a bound record receives data with an invalid shape.
        """
        cfields = cls.__cfields__
        rfields = cls.__rfields__
        annots = cls.__annots__
        condition_index = cls.__dict__.get("__condition_index__")

        cache_key = _bind_context_cache_key(cfields, ctx)
        bound_cache = cls.__dict__.get("__bound_cache__") if cache_key is not None else None
        if cache_key is not None and bound_cache is not None and cache_key in bound_cache:
            return bound_cache[cache_key]

        # Resolve templates and evaluate bound conditions
        resolved = {name: cf.resolve_templates(ctx) for name, cf in cfields.items()}

        # Generate variants with resolved fields & constrained conditional logic
        variants = ConditionalModelMeta._generate_variants(
            cls.__name__,
            rfields,
            resolved,
            annots,
            bind_ctx=ctx,
            base_model=cls,
            condition_index=condition_index,
        )

        # Build namespace for the bound model so Pydantic populates model_fields
        namespace: Dict[str, Any] = {"__annotations__": {}}

        for name in annots:
            if name in rfields:
                typ, val = rfields[name]
                namespace["__annotations__"][name] = typ
                if val is not ...:
                    namespace[name] = val
            elif name in resolved:
                cf = resolved[name]
                if cf.bound_active_result:
                    ftype, finfo = cf.make_field_info()
                    if cf.when or cf.when_any:
                        finfo.default = None
                        finfo._attributes_set["default"] = None
                    namespace["__annotations__"][name] = ftype
                    namespace[name] = finfo

        # Create a subclass of the user's model so methods, validators, and config
        # remain available on the bound class.
        namespace[_GENERATED_CLASS_MARKER] = True
        new_cls = ConditionalModelMeta(f"{cls.__name__}_Bound", (cls,), namespace)
        expected_fields = set(namespace["__annotations__"])
        for field_name in list(new_cls.model_fields):
            if field_name not in expected_fields:
                del new_cls.model_fields[field_name]
        bound_config = dict(getattr(cls, "model_config", {}))
        bound_config["extra"] = "forbid"
        new_cls.model_config = ConfigDict(**bound_config)
        new_cls.model_rebuild(force=True)
        type.__setattr__(new_cls, "__variants__", variants)
        type.__setattr__(new_cls, "__cfields__", resolved)
        type.__setattr__(new_cls, "__rfields__", rfields)
        type.__setattr__(new_cls, "__annots__", annots)
        type.__setattr__(new_cls, "__needs_bind__", False)
        type.__setattr__(new_cls, "__bind_ctx__", ctx)
        type.__setattr__(new_cls, "__condition_index__", condition_index)
        type.__setattr__(
            new_cls, "__active_fields__", frozenset(field_name for variant in variants for field_name in variant.model_fields)
        )

        if cache_key is not None:
            if bound_cache is None:
                bound_cache = {}
                type.__setattr__(cls, "__bound_cache__", bound_cache)
            elif len(bound_cache) >= _BOUND_CACHE_LIMIT:
                bound_cache.pop(next(iter(bound_cache)))
            bound_cache[cache_key] = new_cls

        return new_cls

    @classmethod
    def _get_variants(cls) -> List[Type[BaseModel]]:
        """Get all generated variant models (internal use)."""
        variants = cls.__dict__.get("__variants__")
        if variants is None:
            variants = ConditionalModelMeta._generate_variants(
                cls.__name__,
                cls.__rfields__,
                cls.__cfields__,
                cls.__annots__,
                bind_ctx=getattr(cls, "__bind_ctx__", None),
                base_model=cls,
                condition_index=cls.__dict__.get("__condition_index__"),
            )
            type.__setattr__(cls, "__variants__", variants)
            type.__setattr__(
                cls,
                "__active_fields__",
                frozenset(field_name for variant in variants for field_name in variant.model_fields),
            )
        return variants

    @classmethod
    def _get_active_fields(cls) -> FrozenSet[str]:
        """Return the union of fields present in the generated variants."""
        active_fields = cls.__dict__.get("__active_fields__")
        if active_fields is None:
            cls._get_variants()
            active_fields = cls.__dict__.get("__active_fields__", frozenset())
        return active_fields

    @classmethod
    def _estimate_variant_count(cls) -> int:
        """Estimate the finite runtime branch count without creating models."""
        if getattr(cls, "__needs_bind__", False):
            return 0
        condition_index = cls.__dict__.get("__condition_index__")
        if condition_index is None:
            condition_index = ConditionalModelMeta._build_condition_index(cls.__cfields__, cls.__annots__)
        control_fields = list(condition_index.control_fields)
        control_fields = [
            field_name
            for field_name in control_fields
            if field_name not in cls.__cfields__ or cls.__cfields__[field_name].bound_active_result
        ]
        control_values = _get_control_values(
            control_fields,
            cls.__annots__,
            getattr(cls, "__bind_ctx__", None),
            conditional_fields=cls.__cfields__,
        )
        count = 1
        for field_name in control_fields:
            count *= len(control_values[field_name])
        return count

    @classmethod
    def _as_union(cls) -> Type:
        """Get the model as a Union type of all variants (internal use)."""
        if cls._estimate_variant_count() > _MAX_VARIANTS_FOR_UNION:
            raise ValueError(
                f"Conditional model has more than {_MAX_VARIANTS_FOR_UNION} variants; use json_schema() instead of _as_union()"
            )
        variants = cls._get_variants()
        if len(variants) == 1:
            return variants[0]
        return Union[tuple(variants)]

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = "#/$defs/{model}",
        schema_generator: Any = None,
        mode: str = "validation",
        *,
        union_format: str = "any_of",
    ) -> Dict[str, Any]:
        """Expose the conditional schema through Pydantic's standard API."""
        if getattr(cls, _VARIANT_CLASS_MARKER, False):
            return BaseModel.model_json_schema.__func__(cls, by_alias=by_alias)
        return cls.json_schema(by_alias=by_alias)

    @classmethod
    def json_schema(
        cls, by_alias: bool = False, compact: bool = False, descriptions: bool = True, cache: bool = False
    ) -> Dict[str, Any]:
        """Return the generated JSON Schema for this model.

        Args:
            by_alias: Use field aliases for schema property names.
            compact: Move properties shared by every variant into a definition.
            descriptions: Keep schema description annotations when true.
            cache: Reuse a bounded per-class cache and return defensive copies.

        Returns:
            A JSON-serializable schema dictionary. Multiple runtime variants are
            represented by ``anyOf``; large finite domains use conditional rules.

        Raises:
            ValueError: If bind-time conditions have not been resolved with ``bind``.
        """
        if cls.__needs_bind__:
            raise ValueError(
                "Schema has bind-time conditions (when_bound, when_truthy, "
                "when_falsy, when_unbound, templates, or CSliteral). "
                "Call .bind() first to resolve them."
            )

        if cache:
            cache_key = (by_alias, compact, descriptions)
            schema_cache = cls.__dict__.get("__schema_cache__")
            if schema_cache is None:
                schema_cache = {}
                type.__setattr__(cls, "__schema_cache__", schema_cache)
            if cache_key in schema_cache:
                return copy.deepcopy(schema_cache[cache_key])

        if cls._estimate_variant_count() > _MAX_VARIANTS_FOR_UNION:
            result = _build_conditional_schema(cls, by_alias=by_alias)
            if not descriptions:
                result = _strip_descriptions(result)
            if cache:
                return _cache_schema_result(cls, cache_key, result)
            return result

        variants = cls._get_variants()
        if len(variants) == 1:
            result = variants[0].model_json_schema(by_alias=by_alias)
            if not descriptions:
                result = _strip_descriptions(result)
            if cache:
                return _cache_schema_result(cls, cache_key, result)
            return result

        # Merge variant definitions as each schema is produced.
        merged_defs = {}
        cleaned_schemas = []

        for variant_index, variant in enumerate(variants):
            schema = variant.model_json_schema(by_alias=by_alias)
            cleaned_schemas.append(_merge_variant_schema_definitions(schema, merged_defs, variant_index))

        if compact:
            result = _build_compact_schema(cleaned_schemas, merged_defs)
        else:
            result = {"anyOf": cleaned_schemas}
            if merged_defs:
                result["$defs"] = merged_defs

        if not descriptions:
            result = _strip_descriptions(result)

        if cache:
            return _cache_schema_result(cls, cache_key, result)
        return result

    @staticmethod
    def _collect_nested_models(field_type: Any, models: Set[Type[BaseModel]], visited: Set[int]) -> None:
        """Collect nested models into one accumulator for a traversal."""
        if field_type is None:
            return
        marker = id(field_type)
        if marker in visited:
            return
        visited.add(marker)

        if isinstance(field_type, CSRecordTemplate):
            models.add(field_type.item_schema)
            return
        if isinstance(field_type, type) and issubclass(field_type, BaseModel):
            if getattr(field_type, _DYNAMIC_RECORD_MARKER, False):
                item_schema = getattr(field_type, "__crecord_item_schema__", None)
                if item_schema is not None:
                    models.add(item_schema)
                    return
            models.add(field_type)
            return

        origin = get_origin(field_type)
        if origin is not None:
            for arg in get_args(field_type):
                ConditionalModel._collect_nested_models(arg, models, visited)

    @staticmethod
    def _extract_nested_models(field_type: Any) -> "Set[Type[BaseModel]]":
        """Extract nested models with a bounded cache and one traversal accumulator."""
        try:
            hash(field_type)
        except TypeError:
            cache_key = None
        else:
            cache_key = field_type

        if cache_key is not None and cache_key in _NESTED_MODEL_CACHE:
            return set(_NESTED_MODEL_CACHE[cache_key])

        models: Set[Type[BaseModel]] = set()
        ConditionalModel._collect_nested_models(field_type, models, set())
        result = frozenset(models)
        if cache_key is not None:
            if len(_NESTED_MODEL_CACHE) >= _NESTED_MODEL_CACHE_LIMIT:
                _NESTED_MODEL_CACHE.pop(next(iter(_NESTED_MODEL_CACHE)))
            _NESTED_MODEL_CACHE[cache_key] = result
        return set(result)

    @staticmethod
    def _nested_model_propdoc(model: Type[BaseModel], by_alias: bool = False, ctx: Optional[Dict[str, Any]] = None) -> str:
        if ctx is None:
            ctx = {}
        lines = []
        for field_name, field_info in model.model_fields.items():
            prop_name = (field_info.alias or field_name) if by_alias else field_name
            line = f"  {prop_name}"
            desc = field_info.description
            if desc:
                line += f": {desc}"
            field_type = model.__annotations__.get(field_name)
            if field_type is not None and get_origin(field_type) is Literal:
                opts = ", ".join(str(a) for a in get_args(field_type))
                line += f" (Choose one: {opts})"
            lines.append(line)
        return "\n".join(lines)

    @classmethod
    def propdoc(
        cls,
        by_alias: bool = False,
        lazy: bool = True,
        mention_depends: bool = False,
        mention_options: bool = False,
    ) -> str:
        """Return compact property documentation for this model.

        Args:
            by_alias: Use field aliases in property names and conditions.
            lazy: Include all declared fields when true; otherwise use active fields.
            mention_depends: Include runtime and bind-time condition descriptions.
            mention_options: Include Literal and enum choices in declaration order.

        Returns:
            A newline-separated property description, including nested model fields.

        Raises:
            ValueError: If ``lazy=False`` is requested before bind-time conditions are resolved.
        """
        if not lazy and getattr(cls, "__needs_bind__", False):
            raise ValueError("propdoc(lazy=False) requires a bound model")

        cache_key = (by_alias, lazy, mention_depends, mention_options)
        cache = cls.__dict__.get("__propdoc_cache__")
        if cache is None:
            cache = {}
            type.__setattr__(cls, "__propdoc_cache__", cache)

        if cache_key in cache:
            return cache[cache_key]

        lines = []
        nested_models: Dict[Type[BaseModel], List[str]] = {}  # model -> list of field names using it
        nested_model_is_record: Set[Type[BaseModel]] = set()
        bind_ctx = getattr(cls, "__bind_ctx__", {})
        cfields = getattr(cls, "__cfields__", {})
        rfields = getattr(cls, "__rfields__", {})
        annots = getattr(cls, "__annots__", {})

        active_fields = set(annots.keys()) if lazy else set(cls._get_active_fields())
        alias_map = cls._build_alias_map() if by_alias and mention_depends else {}

        for field_name in annots.keys():
            if field_name not in active_fields:
                continue

            prop_name = field_name
            description = None
            condition_text = ""
            options_text = ""
            field_type = annots.get(field_name)

            if field_name in cfields:
                cond_info = cfields[field_name]

                if by_alias and cond_info.alias:
                    prop_name = cond_info.alias

                if isinstance(cond_info.description, Template):
                    desc_val = cond_info.description.value
                    if isinstance(desc_val, str):
                        description = desc_val
                    elif callable(desc_val):
                        description = "<dynamic>"
                    else:
                        description = str(desc_val)
                else:
                    desc = cond_info.description
                    if isinstance(desc, Template):
                        description = desc.resolve(bind_ctx)
                    else:
                        description = desc

                if mention_depends:
                    condition_text = cls._format_conditions(cond_info, alias_map)

                if mention_options:
                    options_text = cls._get_options_text(cond_info.field_type, cond_info.enum)

                field_type = cond_info.field_type

            elif field_name in rfields:
                _, field_value = rfields[field_name]
                if isinstance(field_value, FieldInfo):
                    if by_alias and field_value.alias:
                        prop_name = field_value.alias
                    description = field_value.description

                if mention_options:
                    options_text = cls._get_options_text(field_type, None)

            else:
                if mention_options:
                    options_text = cls._get_options_text(field_type, None)

            # Collect nested models
            for model in cls._extract_nested_models(field_type):
                nested_models.setdefault(model, []).append(prop_name)
                if isinstance(field_type, CSRecordTemplate) or (
                    isinstance(field_type, type)
                    and issubclass(field_type, BaseModel)
                    and getattr(field_type, _DYNAMIC_RECORD_MARKER, False)
                ):
                    nested_model_is_record.add(model)

            line = prop_name
            if description:
                line += f": {description}"
            if options_text:
                line += f" {options_text}"
            if condition_text:
                line += f" ({condition_text})"
            lines.append(line)

        # Append nested schema docs (each unique model only once)
        if nested_models:
            lines.append("")
            for model, used_by in nested_models.items():
                used_str = ", ".join(used_by)
                if model in nested_model_is_record:
                    lines.append(f"{model.__name__} (record values, used by {used_str}):")
                else:
                    lines.append(f"{model.__name__} (used by {used_str}):")
                inner = cls._nested_model_propdoc(model, by_alias=by_alias, ctx=bind_ctx)
                if inner:
                    lines.append(inner)

        result = "\n".join(lines)
        cache[cache_key] = result
        return result

    @staticmethod
    def _get_options_text(field_type: Any, enum_values: Optional[List]) -> str:
        """Extract options text from Literal types or enum values."""
        options = []
        hashable_options = set()

        def add_option(option: Any) -> None:
            try:
                marker = (type(option), option)
                if marker in hashable_options:
                    return
                hashable_options.add(marker)
            except TypeError:
                if any(existing == option for existing in options if not isinstance(existing, (dict, list, set))):
                    return
                if any(existing == option for existing in options if isinstance(existing, (dict, list, set))):
                    return
            options.append(option)

        if enum_values:
            for option in enum_values:
                add_option(option)
        elif field_type is not None:
            origin = get_origin(field_type)
            if origin is Literal:
                for option in get_args(field_type):
                    add_option(option)
            elif isinstance(field_type, LiteralTemplate):
                if field_type.mapping:
                    for opts in field_type.mapping.values():
                        for option in opts:
                            add_option(option)
                    if field_type.default:
                        for option in field_type.default:
                            add_option(option)
                elif field_type.if_true or field_type.if_false:
                    if field_type.if_true:
                        for option in field_type.if_true:
                            add_option(option)
                    if field_type.if_false:
                        for option in field_type.if_false:
                            add_option(option)

        if options:
            opts_str = ", ".join(str(o) for o in options)
            return f"(Choose one: {opts_str})"
        return ""

    @classmethod
    def _build_alias_map(cls) -> Dict[str, str]:
        """Build a mapping from field names to their aliases."""
        alias_map: Dict[str, str] = {}
        cfields = getattr(cls, "__cfields__", {})
        rfields = getattr(cls, "__rfields__", {})

        for field_name, cond_info in cfields.items():
            if cond_info.alias:
                alias_map[field_name] = cond_info.alias

        for field_name, (_, field_value) in rfields.items():
            if isinstance(field_value, FieldInfo) and field_value.alias:
                alias_map[field_name] = field_value.alias

        return alias_map

    @staticmethod
    def _format_conditions(
        cond_info: "ConditionalFieldInfo",
        alias_map: Optional[Dict[str, str]] = None,
    ) -> str:
        """Format condition information as a readable string."""
        parts = []

        def resolve_name(field: str) -> str:
            if alias_map:
                return alias_map.get(field, field)
            return field

        def format_condition(name: str, value: Any) -> str:
            if isinstance(value, AnyOf):
                vals = ", ".join(str(v) for v in value.get_values())
                return f"{name} is either {vals}"
            elif isinstance(value, NoneOf):
                vals = ", ".join(str(v) for v in value.get_values())
                return f"{name} is neither {vals}"
            else:
                return f"{name} is {value}"

        if cond_info.when:
            when_parts = [format_condition(resolve_name(f), v) for f, v in cond_info.when.items()]
            if when_parts:
                parts.append("only if " + " and ".join(when_parts))

        if cond_info.when_any:
            any_parts = []
            for cond_set in cond_info.when_any:
                set_parts = [format_condition(resolve_name(f), v) for f, v in cond_set.items()]
                if set_parts:
                    any_parts.append("(" + " and ".join(set_parts) + ")")
            if any_parts:
                parts.append("when " + " or ".join(any_parts))

        if cond_info.when_truthy:
            resolved = [resolve_name(f) for f in cond_info.when_truthy]
            parts.append("requires " + ", ".join(resolved))

        if cond_info.when_falsy:
            resolved = [resolve_name(f) for f in cond_info.when_falsy]
            parts.append("requires not " + ", ".join(resolved))

        if cond_info.when_unbound:
            resolved = [resolve_name(f) for f in cond_info.when_unbound]
            parts.append("requires unset " + ", ".join(resolved))

        if cond_info.when_bound:
            bound_parts = []
            for field, value in cond_info.when_bound.items():
                name = resolve_name(field)
                if callable(value) and not isinstance(value, (AnyOf, NoneOf)):
                    bound_parts.append(f"{name} matches condition")
                else:
                    bound_parts.append(format_condition(name, value))
            if bound_parts:
                parts.append("bound " + " and ".join(bound_parts))

        return "; ".join(parts)


__all__ = [
    "CSYesNo",
    "any_of",
    "none_of",
    "truthy",
    "TRUTHY",
    "FALSY",
    "UNBOUND",
    "CStemplate",
    "CSliteral",
    "CSrecord",
    "CSField",
    "ConditionalModel",
    "Template",
    "LiteralTemplate",
    "CSRecord",
    "CSRecordTemplate",
    "AnyOf",
    "NoneOf",
    "ConditionalFieldInfo",
]
