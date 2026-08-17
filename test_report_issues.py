import inspect
from typing import Any, Literal, get_args, get_type_hints

import pytest
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, computed_field, field_validator

from main import (
    CSField,
    CSRecord,
    CSRecordTemplate,
    CSYesNo,
    ConditionalFieldInfo,
    ConditionalModel,
    CStemplate,
    CSliteral,
    CSrecord,
    LiteralTemplate,
    FALSY,
    TRUTHY,
    UNBOUND,
    _build_compact_schema,
    _cache_schema_result,
    _common_schema_properties,
    _merge_variant_schema_definitions,
    _strip_descriptions,
    _generate_combos,
    any_of,
    none_of,
    truthy,
)


def test_bare_required_fields_are_in_variants():
    class Form(ConditionalModel):
        mode: Literal["ready"]
        action: str
        detail: str = CSField(when={"mode": "ready"})

    variant = Form._get_variants()[0]

    assert list(variant.model_fields) == ["mode", "action", "detail"]
    assert set(variant.model_json_schema()["required"]) == {"mode", "action", "detail"}


def test_variants_forbid_inactive_properties():
    class Form(ConditionalModel):
        mode: Literal["a", "b"]
        common: str
        only_a: str = CSField(when={"mode": "a"})

    schemas = Form.json_schema()["anyOf"]
    assert all(schema["additionalProperties"] is False for schema in schemas)
    compact_schemas = Form.json_schema(compact=True)["anyOf"]
    assert all(schema["unevaluatedProperties"] is False for schema in compact_schemas)

    with pytest.raises(ValidationError):
        Form._get_variants()[1].model_validate({"mode": "b", "common": "ok", "only_a": "unexpected"})


def test_controller_domains_are_finite_and_complete():
    class Form(ConditionalModel):
        mode: Literal["new", "edit", "other"]
        detail: str = CSField(
            when_any=[{"mode": any_of("new")}, {"mode": none_of("edit")}],
        )

    variants = Form._get_variants()
    assert [list(variant.model_fields) for variant in variants] == [
        ["mode", "detail"],
        ["mode"],
        ["mode", "detail"],
    ]

    with pytest.raises(ValueError, match="finite Literal, Enum, or bool"):

        class Unbounded(ConditionalModel):
            mode: str
            detail: str = CSField(when={"mode": "edit"})


def test_bind_context_does_not_freeze_unrelated_fields():
    class Form(ConditionalModel):
        mode: Literal["a"]
        name: str
        detail: str = CSField(when={"mode": "a"})

    bound = Form.bind(name="Alice")
    name_schema = bound.json_schema()["properties"]["name"]

    assert "const" not in name_schema
    assert bound.model_validate({"mode": "a", "name": "Bob", "detail": "ok"}).name == "Bob"


def test_inherited_behavior_and_configuration_are_preserved():
    class BaseForm(ConditionalModel):
        model_config = ConfigDict(str_strip_whitespace=True)
        name: str

        @field_validator("name")
        @classmethod
        def name_must_not_be_empty(cls, value: str) -> str:
            if not value:
                raise ValueError("name is required")
            return value

        def label(self) -> str:
            return self.name

        @computed_field
        @property
        def name_length(self) -> int:
            return len(self.name)

    class ChildForm(BaseForm):
        mode: Literal["a"]
        child_value: int

    value = ChildForm.model_validate({"name": "  Alice ", "mode": "a", "child_value": 1})
    assert value.name == "Alice"
    assert value.label() == "Alice"
    assert value.name_length == 5
    assert ChildForm._get_variants()[0].model_config["str_strip_whitespace"] is True

    with pytest.raises(ValidationError):
        ChildForm.model_validate({"name": "", "mode": "a", "child_value": 1})


def test_direct_validation_matches_the_selected_variant():
    class Form(ConditionalModel):
        mode: Literal["a", "b"]
        only_a: str = CSField(when={"mode": "a"})

    assert Form.model_validate({"mode": "b"}).mode == "b"
    with pytest.raises(ValidationError):
        Form.model_validate({"mode": "b", "only_a": "invalid"})
    with pytest.raises(ValidationError):
        Form.model_validate({"mode": "a"})


def test_standard_pydantic_methods_use_the_conditional_shape():
    class Form(ConditionalModel):
        mode: Literal["a", "b"]
        only_a: str | None = CSField(when={"mode": "a"})

    value = Form.model_validate({"mode": "b"})
    assert value.model_dump() == {"mode": "b"}
    assert "only_a" not in value.model_dump_json()
    assert "anyOf" in Form.model_json_schema()

    with pytest.raises(ValidationError):
        Form.model_validate({"mode": "b", "only_a": None})


def test_controller_defaults_are_only_kept_on_matching_variants():
    class Form(ConditionalModel):
        mode: Literal["a", "b"] = "a"
        detail: str = CSField(when={"mode": "b"})

    variants = Form._get_variants()
    matching = next(variant for variant in variants if variant.model_fields["mode"].annotation == Literal["a"])
    conflicting = next(variant for variant in variants if variant.model_fields["mode"].annotation == Literal["b"])
    assert matching.model_validate({}).mode == "a"
    with pytest.raises(ValidationError):
        conflicting.model_validate({})


def test_binding_does_not_freeze_runtime_controller_values():
    class Form(ConditionalModel):
        mode: Literal["a", "b"]
        detail: str = CSField(when={"mode": "a"})

    bound = Form.bind(mode="a")

    assert len(bound._get_variants()) == 2
    assert bound.model_validate({"mode": "b"}).model_dump() == {"mode": "b"}


def test_dynamic_aliases_are_installed_when_binding():
    class Form(ConditionalModel):
        mode: Literal["a"]
        detail: str = CSField(alias=CStemplate("{mode}_detail"), when={"mode": "a"})

    bound = Form.bind(mode="a")

    assert bound.model_fields["detail"].alias == "a_detail"
    assert "a_detail" in bound.model_json_schema()["properties"]


def test_conditional_enum_domains_can_drive_variants():
    class Form(ConditionalModel):
        mode: str = CSField(enum=["a", "b"])
        detail: str = CSField(when={"mode": "a"})

    assert [variant.model_fields["mode"].annotation for variant in Form._get_variants()]
    assert len(Form._get_variants()) == 2


def test_bound_cliteral_domains_can_drive_runtime_conditions():
    class Form(ConditionalModel):
        mode: str = CSField(CSliteral("state", {"ready": ["a", "b"]}))
        detail: str = CSField(when={"mode": "a"})

    bound = Form.bind(state="ready")

    assert len(bound._get_variants()) == 2
    assert set(bound._get_variants()[0].model_fields) != set(bound._get_variants()[1].model_fields)


def test_class_names_and_private_attributes_do_not_change_processing():
    class User_Bound(ConditionalModel):
        value: str

    assert User_Bound._get_variants()
    assert "value" in User_Bound.json_schema()["properties"]

    class WithPrivate(ConditionalModel):
        _token: str = PrivateAttr("secret")
        value: str

    assert WithPrivate(value="ok")._token == "secret"

    NamedBase = type("ConditionalModel", (ConditionalModel,), {"__annotations__": {"value": str}})
    assert NamedBase._get_variants()
    assert "value" in NamedBase.json_schema()["properties"]


def test_enum_enforces_values_and_preserves_schema_extras():
    class Form(ConditionalModel):
        value: str = CSField(enum=["a", "b"], json_schema_extra={"x-note": "keep"})

    schema = Form.json_schema()
    assert schema["properties"]["value"]["enum"] == ["a", "b"]
    assert schema["properties"]["value"]["x-note"] == "keep"
    Form.model_validate({"value": "a"})
    with pytest.raises(ValidationError):
        Form.model_validate({"value": "c"})


def test_description_stripping_preserves_description_property_names():
    class Form(ConditionalModel):
        description: str = CSField(description="property description")
        value: str = CSField(description="field description")

    schema = Form.json_schema(descriptions=False)
    assert "description" in schema["properties"]
    assert "description" not in schema["properties"]["value"]


def test_description_stripping_reuses_unchanged_schema_containers():
    unchanged = {"type": "object", "properties": {"value": {"type": "string"}}}
    assert _strip_descriptions(unchanged) is unchanged

    schema = {
        "type": "object",
        "description": "root",
        "properties": {
            "description": {"type": "string"},
            "value": {"type": "integer", "description": "value"},
        },
    }
    stripped = _strip_descriptions(schema)

    assert stripped is not schema
    assert "description" not in stripped
    assert "description" in stripped["properties"]
    assert "description" not in stripped["properties"]["value"]


def test_literal_braces_and_regex_quantifiers_are_not_implicit_templates():
    class Form(ConditionalModel):
        include: bool
        text: str = CSField(
            description='Example JSON: {"key": 1}',
            pattern=r"^[A-Z]{2}$",
            when_truthy=["include"],
        )

    schema = Form.bind(include=True).json_schema()
    assert schema["properties"]["text"]["description"] == 'Example JSON: {"key": 1}'
    assert schema["properties"]["text"]["pattern"] == r"^[A-Z]{2}$"


def test_unknown_and_cyclic_dependencies_are_rejected():
    with pytest.raises(ValueError, match="unknown conditional dependency"):

        class UnknownDependency(ConditionalModel):
            mode: Literal["ready"]
            detail: str = CSField(when={"missing": "value"})

    with pytest.raises(ValueError, match="cyclic conditional dependency"):

        class CyclicDependency(ConditionalModel):
            first: Literal["yes"] = CSField(when={"second": "yes"})
            second: Literal["yes"] = CSField(when={"first": "yes"})


def test_controller_field_info_is_preserved_in_variants():
    class Form(ConditionalModel):
        mode: Literal["a", "b"] = Field(
            default="a",
            alias="state",
            description="Current state",
            json_schema_extra={"x-source": "input"},
        )
        detail: str = CSField(when={"mode": "a"})

    variant = Form._get_variants()[0]
    schema = variant.model_json_schema(by_alias=True)

    assert schema["properties"]["state"]["description"] == "Current state"
    assert schema["properties"]["state"]["x-source"] == "input"
    assert variant.model_validate({"detail": "ok"}).mode == "a"


def test_public_record_annotations_match_runtime_values():
    from main import CSRecord

    hints = get_type_hints(CSRecord._get_lookup_key)
    assert set(get_args(hints["return"])) == {str, type(None)}
    assert get_type_hints(CSRecord._extract_key)["return"] is Any


def test_combinations_are_streamed():
    combinations = _generate_combos(["mode"], {"mode": ("a", "b")})

    assert iter(combinations) is combinations
    assert list(combinations) == [{"mode": "a"}, {"mode": "b"}]


def test_variant_names_are_typed_and_deterministic():
    class Form(ConditionalModel):
        mode: Literal[1, "1"]
        detail: str = CSField(when={"mode": any_of(1, "1")})

    variants = Form._get_variants()
    names = [variant.__name__ for variant in variants]

    assert len(names) == len(set(names))
    assert all("mode" in name for name in names)


def test_large_controller_sets_use_a_non_cartesian_schema():
    annotations = {f"mode_{index}": bool for index in range(9)}
    annotations.update({f"detail_{index}": str for index in range(9)})
    fields = {f"detail_{index}": CSField(when={f"mode_{index}": True}) for index in range(9)}
    WideForm = type("WideForm", (ConditionalModel,), {"__annotations__": annotations, **fields})

    assert WideForm.__dict__["__variants__"] is None
    schema = WideForm.json_schema()

    assert "anyOf" not in schema
    assert len(schema["allOf"]) == 9


def test_conditional_model_uses_explicit_pydantic_v2_configuration():
    assert ConditionalModel.model_config["extra"] == "forbid"
    assert ConditionalModel.model_config["populate_by_name"] is True
    assert not hasattr(ConditionalModel, "Config")


def test_conditional_dependencies_are_evaluated_in_topological_order(monkeypatch):
    calls = []

    class Form(ConditionalModel):
        mode: Literal["on"]
        leaf: str = CSField(when={"middle": "on"})
        middle: Literal["on"] = CSField(when={"root": "on"})
        root: Literal["on"] = CSField(when={"mode": "on"})

    original_evaluate = ConditionalFieldInfo.evaluate

    def record_evaluate(self, combo):
        calls.append(self)
        return original_evaluate(self, combo)

    monkeypatch.setattr(ConditionalFieldInfo, "evaluate", record_evaluate)
    variant = Form._get_variants()[0]

    assert list(variant.model_fields) == ["mode", "leaf", "middle", "root"]
    assert len(calls) == 3
    index = Form.__dict__["__condition_index__"]
    assert index.dependency_order == ("root", "middle", "leaf")
    assert index.dependents["root"] == ("middle",)


def test_condition_index_reuses_controller_domains():
    class Form(ConditionalModel):
        mode: Literal["a", "b"]
        detail: str = CSField(when={"mode": any_of("a", "b")})

    index = Form.__dict__["__condition_index__"]

    assert index.control_fields == ("mode",)
    assert index.condition_values["mode"] == ("a", "b")
    assert Form._estimate_variant_count() == 2


def test_bind_reuses_models_for_hashable_contexts():
    class Form(ConditionalModel):
        detail: str = CSField(when_truthy=["show"])

    first = Form.bind(show=True)
    second = Form.bind(show=True)
    uncacheable = Form.bind(show=[True])

    assert first is second
    assert uncacheable is not first


def test_variant_identity_uses_typed_controller_values():
    class Form(ConditionalModel):
        mode: Literal[1, "1"]
        detail: str = CSField(when={"mode": any_of(1, "1")})

    variants = Form._get_variants()

    assert len(variants) == 2
    assert {variant.model_fields["mode"].annotation for variant in variants} == {Literal[1], Literal["1"]}


def test_any_of_and_none_of_support_unhashable_values():
    values = [{"kind": "a"}, [1, 2]]

    assert any_of(*values).evaluate({"kind": "a"})
    assert any_of(*values).evaluate([1, 2])
    assert not none_of(*values).evaluate({"kind": "a"})
    assert none_of(*values).evaluate({"kind": "other"})


def test_bind_conditions_distinguish_missing_none_and_falsy_values():
    class Form(ConditionalModel):
        unbound: str = CSField(when_unbound=["flag"])
        falsy: str = CSField(when_falsy=["flag"])
        explicit_none: str = CSField(when_bound={"flag": None})

    absent = Form.bind()
    none_value = Form.bind(flag=None)
    false_value = Form.bind(flag=False)

    assert list(absent._get_variants()[0].model_fields) == ["unbound"]
    assert set(none_value._get_variants()[0].model_fields) == {"falsy", "explicit_none"}
    assert list(false_value._get_variants()[0].model_fields) == ["falsy"]


def test_cliteral_condition_is_called_once_when_options_are_missing():
    calls = []

    def condition(value):
        calls.append(value)
        return True

    from main import CSliteral

    literal = CSliteral("mode", condition, if_true=None, if_false=["fallback"])
    with pytest.raises(ValueError, match="corresponding options list"):
        literal.resolve({"mode": "value"})

    assert calls == ["value"]


def test_crecord_freezes_input_and_defends_data_map():
    class Item(BaseModel):
        key: str
        value: int

    source = [{"key": "one", "value": 1}]
    record = CSRecord(source, "key", Item)
    source[0]["key"] = "changed"
    source[0]["value"] = 2

    exposed = record.data_map
    exposed["one"]["value"] = 99

    assert record.keys == ["one"]
    assert record.data_map["one"]["value"] == 1
    assert "one" in record.model().model_fields


def test_crecord_flatten_preserves_alias_schema_and_constraints():
    class Item(BaseModel):
        value: int = Field(alias="itemValue", ge=1, le=10)

    record = CSRecord(
        [{"name": "one"}],
        lambda item: item["name"],
        Item,
        flatten=True,
    )

    schema = record.json_schema(by_alias=True)
    item_schema = schema["$defs"]["CSRecordItem"]
    assert schema["properties"]["one"] == {"$ref": "#/$defs/CSRecordItem"}
    assert item_schema["minimum"] == 1
    assert item_schema["maximum"] == 10

    model = record.model()
    assert model.model_json_schema()["properties"]["one"]["minimum"] == 1
    model.model_validate({"one": 5})
    with pytest.raises(ValidationError):
        model.model_validate({"one": 0})


def test_crecord_hoists_nested_defs_and_matches_extra_policy():
    class Nested(BaseModel):
        label: str

    class Item(BaseModel):
        nested: Nested

    strict = CSRecord(
        {
            "one": {"nested": {"label": "x"}},
            "two": {"nested": {"label": "y"}},
        },
        "ignored",
        Item,
    )
    schema = strict.json_schema()

    assert "$defs" in schema
    assert "$defs" not in schema["$defs"]["CSRecordItem"]
    assert "Nested" in schema["$defs"]
    assert schema["properties"]["one"] is not schema["properties"]["two"]
    with pytest.raises(ValidationError):
        strict.model().model_validate({"one": {"nested": {"label": "x"}}, "extra": {}})

    permissive = CSRecord(
        {"one": {"nested": {"label": "x"}}},
        "ignored",
        Item,
        additional_properties=True,
    )
    value = permissive.model().model_validate({"one": {"nested": {"label": "x"}}, "extra": {"anything": True}})
    assert value.one.nested.label == "x"


def test_dynamic_record_marker_does_not_use_class_name_heuristics():
    class DynamicRecord(BaseModel):
        value: int

    assert ConditionalModel._extract_nested_models(DynamicRecord) == {DynamicRecord}

    class Item(BaseModel):
        value: int

    record_model = CSRecord({"one": {"value": 1}}, "ignored", Item).model()
    assert getattr(record_model, "__conditional_dynamic_record__") is True
    assert ConditionalModel._extract_nested_models(record_model) == {Item}


def test_variant_definition_collisions_are_namespaced_and_refs_rewritten():
    first = {
        "$defs": {"Shared": {"type": "string"}},
        "properties": {"value": {"$ref": "#/$defs/Shared"}},
    }
    second = {
        "$defs": {"Shared": {"type": "integer"}},
        "properties": {"value": {"$ref": "#/$defs/Shared"}},
    }
    merged = {}

    first_clean = _merge_variant_schema_definitions(first, merged, 0)
    second_clean = _merge_variant_schema_definitions(second, merged, 1)

    assert merged["Shared"]["type"] == "string"
    assert merged["Shared_2"]["type"] == "integer"
    assert first_clean["properties"]["value"]["$ref"] == "#/$defs/Shared"
    assert second_clean["properties"]["value"]["$ref"] == "#/$defs/Shared_2"


def test_transitive_variant_definition_collisions_rewrite_nested_refs():
    first = {
        "$defs": {
            "Shared": {"type": "string"},
            "Wrapper": {"properties": {"value": {"$ref": "#/$defs/Shared"}}},
        },
        "properties": {"value": {"$ref": "#/$defs/Wrapper"}},
    }
    second = {
        "$defs": {
            "Shared": {"type": "integer"},
            "Wrapper": {"properties": {"value": {"$ref": "#/$defs/Shared"}}},
        },
        "properties": {"value": {"$ref": "#/$defs/Wrapper"}},
    }
    merged = {}

    _merge_variant_schema_definitions(first, merged, 0)
    second_clean = _merge_variant_schema_definitions(second, merged, 1)

    assert second_clean["properties"]["value"]["$ref"] == "#/$defs/Wrapper_2"
    assert merged["Wrapper_2"]["properties"]["value"]["$ref"] == "#/$defs/Shared_2"


def test_compact_schema_does_not_overwrite_existing_internal_name():
    variants = [
        {"properties": {"common": {"type": "string"}}, "required": ["common"]},
        {"properties": {"common": {"type": "string"}}, "required": ["common"]},
    ]
    schema = _build_compact_schema(
        variants,
        {"__conditional_base__": {"type": "integer"}},
    )

    assert schema["$defs"]["__conditional_base__"]["type"] == "integer"
    ref = schema["anyOf"][0]["$ref"]
    assert ref == "#/$defs/__conditional_base___"


def test_compact_schema_uses_ordered_structural_common_property_matching():
    variants = [
        {"properties": {"first": {"type": "object", "properties": {"value": {"type": "string"}}}}},
        {"properties": {"first": {"type": "object", "properties": {"value": {"type": "string"}}}}},
    ]

    common = _common_schema_properties(variants)

    assert list(common) == ["first"]


def test_schema_cache_is_bounded_and_returns_private_copies():
    class Form(ConditionalModel):
        value: str

    for index in range(10):
        result = _cache_schema_result(Form, (bool(index % 2), bool(index // 2), True), {"index": index})
        result["index"] = -1

    cache = Form.__dict__["__schema_cache__"]
    assert len(cache) <= 8
    assert all(value["index"] >= 0 for value in cache.values())


def test_schema_and_propdoc_caches_are_owned_by_each_class():
    class Parent(ConditionalModel):
        name: str

    cached = Parent.json_schema(cache=True)
    cached["properties"]["name"]["type"] = "invalid"
    assert Parent.json_schema(cache=True)["properties"]["name"]["type"] == "string"

    class Child(Parent):
        age: int

    assert "age" in Child.json_schema(cache=True)["properties"]
    Parent.propdoc()
    assert "age" in Child.propdoc()


def test_propdoc_lazy_controls_bound_field_filtering():
    class Form(ConditionalModel):
        show: bool
        detail: str = CSField(when_truthy=["show"])

    assert "detail" in Form.propdoc(lazy=True)
    with pytest.raises(ValueError, match="requires a bound model"):
        Form.propdoc(lazy=False)

    shown = Form.bind(show=True)
    hidden = Form.bind(show=False)
    assert "detail" in shown.propdoc(lazy=False)
    assert "detail" not in hidden.propdoc(lazy=False)
    assert "detail" in hidden.propdoc(lazy=True)


def test_propdoc_builds_alias_map_once(monkeypatch):
    class Form(ConditionalModel):
        mode: Literal["a"] = Field(alias="state")
        detail: str = CSField(alias="details", when={"mode": "a"})

    calls = []
    original = Form._build_alias_map.__func__

    def build_alias_map(cls):
        calls.append(True)
        return original(cls)

    monkeypatch.setattr(Form, "_build_alias_map", classmethod(build_alias_map))
    Form.propdoc(by_alias=True, mention_depends=True)

    assert len(calls) == 1


def test_propdoc_options_preserve_order_for_mixed_values():
    literal = LiteralTemplate("mode", {"a": [1, "one"]}, [False, 1])

    options = ConditionalModel._get_options_text(literal, None)

    assert options == "(Choose one: 1, one, False)"


def test_nested_propdoc_context_default_is_none():
    parameter = inspect.signature(ConditionalModel._nested_model_propdoc).parameters["ctx"]

    assert parameter.default is None


def test_nested_model_extraction_reuses_cached_accumulator_result(monkeypatch):
    class Item(BaseModel):
        value: str

    nested_type = list[dict[str, Item]]
    calls = []
    original = ConditionalModel._collect_nested_models

    def collect(field_type, models, visited):
        calls.append(field_type)
        return original(field_type, models, visited)

    monkeypatch.setattr(ConditionalModel, "_collect_nested_models", staticmethod(collect))
    assert ConditionalModel._extract_nested_models(nested_type) == {Item}
    assert len(calls) > 1
    calls.clear()

    assert ConditionalModel._extract_nested_models(nested_type) == {Item}
    assert calls == []


def test_snake_case_factories_and_focused_modules_preserve_api():
    from conditions import AnyOf as ModuleAnyOf
    from records import CSRecord as ModuleCRecord
    from templates import Template as ModuleTemplate

    assert ModuleAnyOf is any_of("x").__class__
    assert ModuleCRecord is CSRecord
    assert ModuleTemplate is CStemplate("{value}").__class__

    class Form(ConditionalModel):
        mode: Literal["ready"]
        detail: str = CSField(when={"mode": "ready"})

    assert "detail" in Form.json_schema()["properties"]


def test_legacy_names_are_available_from_compat():
    from compat import (
        CField,
        CRecord,
        CRecordTemplate,
        CYesNo,
        Cliteral,
        Crecord,
        Ctemplate,
        c_field,
        c_literal,
        c_record,
        c_template,
    )

    assert CField is CSField
    assert CRecord is CSRecord
    assert CRecordTemplate is CSRecordTemplate
    assert CYesNo is CSYesNo
    assert Cliteral is CSliteral
    assert Crecord is CSrecord
    assert Ctemplate is CStemplate
    assert c_field is CSField
    assert c_literal is CSliteral
    assert c_record is CSrecord
    assert c_template is CStemplate


def test_snake_case_factories_are_not_primary_exports():
    import main
    import records
    import templates

    for module in (main, records, templates):
        assert not hasattr(module, "c_template")
        assert not hasattr(module, "c_literal")
        assert not hasattr(module, "c_record")
        assert not hasattr(module, "c_field")


def test_condition_sentinels_use_the_shared_presence_evaluator():
    class Form(ConditionalModel):
        truthy_field: str = CSField(when_bound={"flag": TRUTHY})
        falsy_field: str = CSField(when_bound={"flag": FALSY})
        unbound_field: str = CSField(when_bound={"flag": UNBOUND})

    absent_fields = set(Form.bind()._get_variants()[0].model_fields)
    true_fields = set(Form.bind(flag=True)._get_variants()[0].model_fields)
    false_fields = set(Form.bind(flag=False)._get_variants()[0].model_fields)

    assert absent_fields == {"unbound_field"}
    assert true_fields == {"truthy_field"}
    assert false_fields == {"falsy_field"}
    assert truthy(1) is True


def test_runtime_conditions_require_canonical_field_names():
    with pytest.raises(ValueError, match="field name"):

        class AliasCondition(ConditionalModel):
            mode: Literal["a"] = Field(alias="state")
            detail: str = CSField(when={"state": "a"})

    with pytest.raises(ValueError, match="ambiguous alias"):

        class AmbiguousAlias(ConditionalModel):
            first: str = Field(alias="second")
            second: str


def test_crecord_rejects_malformed_and_duplicate_keys():
    from pydantic import BaseModel

    class Item(BaseModel):
        name: str

    with pytest.raises(TypeError, match="each item must be a dictionary"):
        CSRecord(data=["bad"], key_field="name", item_schema=Item)

    with pytest.raises(TypeError, match="values must be dictionaries"):
        CSRecord(data={"one": "bad"}, key_field="name", item_schema=Item)

    with pytest.raises(ValueError, match="missing key"):
        CSRecord(data=[{}], key_field="name", item_schema=Item).keys

    with pytest.raises(ValueError, match="duplicate key"):
        CSRecord(
            data=[{"name": "one"}, {"name": "one"}],
            key_field="name",
            item_schema=Item,
        ).keys

    with pytest.raises(ValueError, match="must be a string"):
        CSRecord(data=[{"name": "one"}], key_field=lambda item: [item["name"], "key"], item_schema=Item).keys
