## API Reference

### CField Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `field_type` | `Type \| Cliteral` | Field type (can be inferred from annotation) |
| `when` | `Dict[str, Any]` | Runtime conditions using field NAMES (all must match) |
| `when_any` | `List[Dict]` | OR conditions using field NAMES (any must match) |
| `when_bound` | `Dict \| List` | Bind-time conditions (dict) or truthy checks (list) |
| `when_truthy` | `List[str]` | Context keys that must be truthy |
| `when_falsy` | `List[str]` | Context keys that must be falsy |
| `when_unbound` | `List[str]` | Context keys that must NOT be present |
| `default` | `Any` | Default value |
| `alias` | `str` | JSON alias (used with `by_alias=True`) |
| `description` | `str \| Template` | Field description |
| `pattern` | `str \| Template` | Regex pattern |
| `enum` | `List \| Template` | Enum values |

### ConditionalModel Methods

| Method | Description |
|--------|-------------|
| `.bind(**ctx)` | Resolve templates and bind-time conditions |
| `.get_variants()` | Get list of variant models |
| `.as_union()` | Get Union type of all variants |
| `.json_schema(by_alias=False)` | Get JSON schema (with anyOf if multiple variants) |

### Condition Helpers

| Helper | Description |
|--------|-------------|
| `any_of(*values)` | Match if value is ANY of the given options |
| `none_of(*values)` | Match if value is NONE of the given options |
| `Cliteral(key, mapping, default)` | State-dependent Literal type |
| `Ctemplate(value)` | Template for dynamic strings/values |
| `TRUTHY` | Sentinel for truthy check in dict conditions |
| `FALSY` | Sentinel for falsy check in dict conditions |
