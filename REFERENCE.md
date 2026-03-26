## API Reference

### CField Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `field_type` | `Type \| Cliteral \| None` | Field type (omit or use `...` to infer from annotation) |
| `when` | `Dict[str, Any]` | Runtime conditions using field NAMES (all must match) |
| `when_any` | `List[Dict]` | OR conditions using field NAMES (any must match) |
| `when_bound` | `Dict \| List` | Bind-time conditions (dict) or truthy checks (list) |
| `when_truthy` | `List[str]` | Context keys that must be truthy |
| `when_falsy` | `List[str]` | Context keys that must be falsy |
| `when_unbound` | `List[str]` | Context keys that must NOT be present |
| `default` | `Any` | Default value |
| `alias` | `str` | JSON alias (used with `by_alias=True`) |
| `description` | `str \| Template` | Field description (may contain `{placeholder}` templates resolved at bind time) |
| `pattern` | `str \| Template` | Regex pattern |
| `enum` | `List \| Template` | Enum values |

### ConditionalModel Methods

| Method | Description |
|--------|-------------|
| `.bind(**ctx)` | Resolve templates and bind-time conditions |
| `._get_variants()` | Get list of variant models (internal use) |
| `._as_union()` | Get Union type of all variants (internal use) |
| `.json_schema(by_alias=False, compact=False)` | Get JSON schema (with anyOf if multiple variants) |
| `.propdoc(by_alias=False, lazy=True, mention_depends=False, mention_options=False)` | Get a human-readable string of property names and descriptions |

#### `json_schema(compact=True)`

When `compact=True`, fields with identical schemas across all variants are extracted into a shared `$defs/Base` definition. Each variant in `anyOf` then uses `allOf [$ref, variant-specific]` instead of repeating shared properties, reducing schema size proportionally to the number of shared fields and variants.

```python
class Form(ConditionalModel):
    name: str = CField(str)
    mode: Literal["a", "b", "c"] = CField(str, when={"flag": True})
    mode: Literal["x"] = CField(str, when={"flag": False})

# Standard schema repeats `name` in each variant
Form.json_schema()
# {"anyOf": [{"properties": {"name": ..., "mode": ...}}, ...]}

# Compact schema extracts `name` to $defs/Base
Form.json_schema(compact=True)
# {"anyOf": [{"allOf": [{"$ref": "#/$defs/Base"}, {"properties": {"mode": ...}}]}, ...], "$defs": {"Base": {"properties": {"name": ...}}}}
```

#### `propdoc()`

Returns a multi-line string with property names and descriptions. Useful for injecting field documentation into LLM prompts.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `by_alias` | `False` | Use field aliases instead of field names |
| `lazy` | `True` | Include all properties regardless of bind-time conditions |
| `mention_depends` | `False` | Append condition text like `(only if x is y)` |
| `mention_options` | `False` | Append available options for Literal/enum fields |

```python
class Form(ConditionalModel):
    name: str = CField(alias="userName", description="User's full name")
    age: int = CField(description="User's age", when={"has_age": True})

print(Form.propdoc())
# name: User's full name
# age: User's age

print(Form.propdoc(by_alias=True, mention_depends=True))
# userName: User's full name
# age: User's age (only if has_age is True)
```

Nested `BaseModel` fields are automatically documented below the main properties. Results are cached per class and parameter combination.

### Condition Helpers

| Helper | Description |
|--------|-------------|
| `any_of(*values)` | Match if value is ANY of the given options |
| `none_of(*values)` | Match if value is NONE of the given options |
| `Cliteral(key, mapping, default)` | State-dependent Literal type (mapping mode) |
| `Cliteral(key, condition, if_true=, if_false=)` | State-dependent Literal type (conditional mode) |
| `Ctemplate(value)` | Template for dynamic strings/values |

### Template Placeholders in Literals

Literal values can contain `{placeholder}` templates that are resolved at bind time:

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
| `flatten` | `bool` | If `item_schema` has exactly one field, use that field's type directly as property values (default: False) |
| `additional_properties` | `bool` | Allow additional properties (default: False) |

**Flatten mode** - when `item_schema` has exactly one field, property values use that field's type directly instead of a nested object:

```python
class Score(BaseModel):
    value: int

record = CRecord(data=scores, key_field="name", item_schema=Score, flatten=True)
# {"type": "object", "properties": {"alice": {"type": "integer"}, ...}}
# Instead of: {"properties": {"alice": {"type": "object", "properties": {"value": ...}}}}
```

**Key extraction modes:**
```python
# Field name lookup
CRecord(data, key_field="item_name", ...)

# Alias lookup (uses model field's alias)
CRecord(data, key_field="item_name", use_alias=True, ...)

# Custom callable
CRecord(data, key_field=lambda item: item["name"].lower(), ...)
```
