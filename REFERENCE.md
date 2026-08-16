## API Reference

### Supported Versions

The project targets Python 3.10 and newer with Pydantic v2 (`>=2,<3`). The
development extras provide the supported test, Ruff, and Pyrefly tooling.

Run the baseline checks with:

```bash
python -m pytest
ruff format --check .
ruff check .
pyrefly check
```

Install the development tools with `python -m pip install -e '.[dev]'`.

### Public Exports

The supported public names are `CYesNo`, `AnyOf`, `NoneOf`, `any_of`,
`none_of`, `truthy`, `TRUTHY`, `FALSY`, `UNBOUND`, `Template`,
`LiteralTemplate`, `Ctemplate`, `Cliteral`, `CRecord`, `CRecordTemplate`,
`Crecord`, `CField`, `ConditionalFieldInfo`, and `ConditionalModel`. The
snake_case aliases `c_template`, `c_literal`, `c_record`, and `c_field` are
preferred for new code. All names are available from `main`; subsystem names
are also re-exported by their focused modules.

### CField Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `field_type` | `Type \| LiteralTemplate \| CRecordTemplate \| None` | Field type (omit or use `...` to infer from annotation) |
| `when` | `Dict[str, Any]` | Runtime conditions using field NAMES (all must match) |
| `when_any` | `List[Dict[str, Any]]` | OR conditions using field NAMES (any must match) |
| `when_bound` | `Dict \| List` | Bind-time conditions (dict) or truthy checks (list) |
| `when_truthy` | `List[str]` | Context keys that must be truthy |
| `when_falsy` | `List[str]` | Context keys that must be falsy |
| `when_unbound` | `List[str]` | Context keys that must NOT be present |
| `default` | `Any` | Default value |
| `alias` | `str` | JSON alias (used with `by_alias=True`) |
| `description` | `str \| Template` | Field description |
| `pattern` | `str \| Template` | Regex pattern |
| `enum` | `List \| Template` | Allowed values enforced during validation and emitted in the schema |
| `**field_kwargs` | `Field` arguments | Additional Pydantic field metadata and constraints |

Runtime `when` and `when_any` keys must be Python field names, never aliases.
Aliases that collide with another field name or alias are rejected at class
creation.

### ConditionalModel Methods

| Method | Description |
|--------|-------------|
| `.bind(**ctx)` | Resolve templates and bind-time conditions |
| `._get_variants()` | Get list of variant models (internal use) |
| `._as_union()` | Get Union type of all variants (internal use) |
| `.model_validate(...)` / `.model_dump(...)` | Validate and serialize using the selected conditional variant |
| `.model_json_schema(...)` | Standard Pydantic schema method with conditional variants |
| `.json_schema(by_alias=False, compact=False, descriptions=True, cache=False)` | Get JSON schema (with `anyOf` if multiple variants) and control schema size, descriptions, and caching |
| `.propdoc(by_alias=False, lazy=True, mention_depends=False, mention_options=False)` | Get compact property documentation, including nested model fields |

### Condition Helpers

| Helper | Description |
|--------|-------------|
| `any_of(*values)` | Match if value is ANY of the given options |
| `none_of(*values)` | Match if value is NONE of the given options |
| `AnyOf(*values)` | Condition object returned by `any_of` |
| `NoneOf(*values)` | Condition object returned by `none_of` |
| `truthy(value)` | Return `bool(value)` for a direct truthiness check |
| `Cliteral(key, mapping, default)` | State-dependent Literal type (mapping mode) |
| `Cliteral(key, condition, if_true=, if_false=)` | State-dependent Literal type (conditional mode) |
| `Ctemplate(value)` | Template for dynamic strings/values |

`TRUTHY`, `FALSY`, and `UNBOUND` are sentinel values for `when_bound` mappings.
`TRUTHY` and `FALSY` require a present context key with the corresponding
boolean state; `UNBOUND` requires that the key is absent. A missing key is not
treated as falsy or equal to `None`.

### Template Placeholders in Literals

Literal values can contain simple `{placeholder}` templates that are resolved at bind time:

```python
# Template in regular Literal (type inferred from annotation)
guide: Literal["I will answer in {language} as {char_name}."] = CField(
    when_truthy=["language", "char_name"]
)
# bind(language="English", char_name="Claude")
# -> Literal["I will answer in English as Claude."]

# Template in Cliteral values
action: str = CField(
    Cliteral("mode", {
        "chat": ["Reply as {char_name}"],
        "formal": ["Respond formally"],
    }),
    when_truthy=["mode"]
)
```

Bind-time templates can also be used in field aliases, descriptions, patterns, and enum values. These values are resolved by `ConditionalModel.bind(**context)` before the bound schema is generated. Bind context resolves templates and predicates; it does not pre-fill or freeze runtime controller fields.

Braces in ordinary strings are treated literally. Use `Ctemplate(...)` when a description, alias, pattern, or other general string should be formatted from bind context.

### JSON Schema Output Options

`ConditionalModel.json_schema()` supports additional output controls:

```python
# Extract properties shared by every variant into $defs/Base.
schema = BoundForm.json_schema(compact=True)

# Omit descriptions recursively for a smaller schema.
schema = BoundForm.json_schema(descriptions=False)

# Reuse the generated result when the same bound class is queried repeatedly.
schema = BoundForm.json_schema(cache=True)
```

`compact=True` is most useful for models with multiple variants. The compact form uses `allOf` references to share common properties. Cache keys include `by_alias`, `compact`, and `descriptions`.

When `cache=True`, each call returns a defensive copy, so mutating a returned
schema does not affect later calls or subclasses.

For models whose finite controller combinations exceed the internal variant limit, `json_schema()` emits `if`/`then`/`else` rules instead of constructing a Cartesian-product `anyOf`. `_as_union()` is capped for those large models; use the JSON Schema output for them.

Generated variants reject properties that are inactive for the selected condition. Runtime controller fields must use a finite `Literal`, `Enum`, or `bool` annotation so every possible branch can be represented. A conditional field's finite `enum` metadata and a bound `Cliteral` are also used when discovering controller domains.

### Cliteral Modes

**Mapping mode** - map context values to literal options:
```python
action: str = CField(
    Cliteral("mode", {
        "create": ["save", "cancel"],
        "edit": ["save", "delete", "cancel"],
    }, default=["ok"]),
    when_truthy=["mode"]
)
```

**Conditional mode** - use lambda to choose between two option lists:
```python
location_type: str = CField(
    Cliteral("location",
             lambda loc: len(loc) > 10,
             if_true=["Long location"],
             if_false=["Short location"]),
    when_truthy=["location"]
)
```

### CRecord - Dynamic Object Schemas from Data

Create object schemas where property names come from runtime data:

**Standalone usage with CRecord:**
```python
from main import CRecord

old_armor = [
    {"armor_item_name": "helmet", "defense": 10},
    {"armor_item_name": "chestplate", "defense": 25},
]

record = CRecord(
    data=old_armor,
    key_field="armor_item_name",
    item_schema=UpdatableArmorItemModel,
)

# Get schema
schema = record.json_schema()
# {"type": "object", "properties": {"helmet": {...}, "chestplate": {...}}}

# Access original data
record.data_map  # {"helmet": {"armor_item_name": "helmet", ...}, ...}
record.keys      # ["helmet", "chestplate"]
```

**Bind-time usage with Crecord:**
```python
class UpdateArmorForm(ConditionalModel):
    armor_updates: dict = CField(
        Crecord("armor_data", "armor_item_name", UpdatableArmorItemModel),
        when_truthy=["armor_data"]
    )

BoundForm = UpdateArmorForm.bind(armor_data=old_armor)
schema = BoundForm.json_schema()
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `data` / `data_key` | `List[Dict] \| Dict[str, Dict]` / `str` | Data or context key |
| `key_field` | `str \| Callable` | Field name or function to extract property names |
| `item_schema` | `Type[BaseModel]` | Schema for each property's value |
| `use_alias` | `bool` | Use field alias for key lookup (default: False) |
| `required` | `bool` | Make all properties required (default: True) |
| `flatten` | `bool` | If the item model has one field, use that field's schema directly for each record value (default: False) |
| `additional_properties` | `bool` | Allow additional properties (default: False) |

**Key extraction modes:**
```python
# Field name lookup
CRecord(data, key_field="item_name", ...)

# Alias lookup (uses model field's alias)
CRecord(data, key_field="item_name", use_alias=True, ...)

# Custom callable
CRecord(data, key_field=lambda item: item["name"].lower(), ...)
```

**Flattening single-field item models:**

```python
class SettingValue(BaseModel):
    value: int

record = CRecord(
    data=[{"name": "retries"}],
    key_field="name",
    item_schema=SettingValue,
    flatten=True,
)

# Each record property uses the integer schema directly rather than
# requiring {"value": ...}.
```

The same `flatten` option is available on `Crecord(...)` for bind-time records.

Record input must contain dictionaries with string property keys. List records
must provide a non-missing, unique string key for every item; malformed items,
missing keys, duplicate keys, and invalid callable results raise an error.
Input is copied when the record is created, and `data_map` returns a defensive
copy, so changing source data or an accessed mapping cannot invalidate the
cached model or schema. Dynamic properties reference one canonical item
definition under the record schema's root `$defs`; flattened fields preserve
aliases, constraints, and requiredness. The dynamic model uses the same
`additional_properties` policy as the standalone schema.

### Property Documentation

`propdoc()` produces a compact text representation of the active properties. It can use aliases, include condition descriptions, and show Literal or enum options with `mention_options=True`. Nested `BaseModel` fields are listed once below the parent properties; dynamic record item models are labeled as record values.

With the default `lazy=True`, documentation includes every declared property,
including properties removed by a bound condition. `lazy=False` reports only
properties present in the generated variants and therefore requires a bound
model when bind-time conditions are used. Options retain declaration order,
including heterogeneous Literal values.

```python
print(BoundForm.propdoc(by_alias=True, mention_depends=True, mention_options=True))
```

### Public Contracts and Errors

Runtime condition keys are Python field names, not aliases. Unknown or cyclic
dependencies and ambiguous aliases raise `ValueError` while the model class is
created. Runtime controllers must be finite `Literal`, `Enum`, or `bool`
annotations; other annotations raise `ValueError` before variants are built.
`when_bound` must be a mapping or list and raises `TypeError` otherwise.

`Ctemplate` formats strings with the supplied bind context. Missing formatting
keys and exceptions raised by callable templates propagate from `bind()`.
Implicit formatting is limited to simple placeholders inside Literal values;
ordinary braces in other strings are literal. `Cliteral.resolve()` raises
`ValueError` when the selected mapping has no options or an empty option list.

`CRecord` accepts either `List[Dict[str, Any]]` or
`Dict[str, Dict[str, Any]]`. It copies input at construction. List records must
produce a unique, non-missing string key for every item; malformed containers,
items, dictionary keys/values, missing keys, duplicate keys, and invalid
callable results raise `TypeError` or `ValueError` with the failing boundary
identified. `data_map` is a defensive copy, and `keys` preserves input order.
`CRecordTemplate.resolve()` returns `dict` when its context key is absent and
otherwise propagates the same record validation errors.

`ConditionalModel.bind()` returns a model subclass and resolves templates,
records, and bind-time conditions. `json_schema()` raises `ValueError` when
called before required binding. `propdoc(lazy=False)` likewise requires a
bound model. Cached schemas are bounded and every returned schema is a
defensive copy; uncached schemas are also newly generated dictionaries.

`CField()` returns a `ConditionalFieldInfo` descriptor; direct descriptor
construction is supported for advanced integrations but normal model code
should use `CField`. `Template`, `LiteralTemplate`, `CRecordTemplate`, and
`ConditionalFieldInfo` retain their input metadata until `bind()` resolves it;
they do not mutate the caller's context mapping.

### Module and Naming Compatibility

The original `main` import path remains supported. Subsystem imports are also
available from `conditions`, `templates`, `records`, and `schema`. The
snake_case factory names `c_template`, `c_literal`, `c_record`, and `c_field`
are preferred for new code; `Ctemplate`, `Cliteral`, `Crecord`, and `CField`
remain compatibility aliases.
