# Conditional Schema

ConditionalSchema is a Python library for conditional field schemas in LLM structured output. It extends Pydantic v2 models so a field can exist only when a condition holds: when another field takes a given value, or when the caller supplies a context. One pydantic-style definition produces both outputs a generation pipeline needs: a compact, token-efficient property list for the prompt, and a trimmed JSON Schema for the structured-output API or a validator.

## What it fixes

1. Pydantic cannot express "field A exists only when condition B is valid". The standard workaround is hand-written `anyOf` branches, which repeat every shared property once per branch and grow with each new combination.
2. Oversized schemas. Standard JSON Schema output carries a description and title for every property. That text, when provided to an inference engine does not help a model fill in values, but it still ships on every request incereasing payload size and network and parsing latency. This library splits token-efficient field descriptions for prompt and schema structure for schema guidance.
3. Handling property names can be confusing when you have to at the same time optimize them for: code maintainability, token efficiency, schema output accuracy and customization. This is resolved by using property names only for code, aliases only for LLM, templates in aliases add flexibility without breaking anything.
4. Static definitions. A fixed class cannot react to per-request context such as preferred language or status, and cannot describe objects whose property names exist only in runtime data.

## Concept

A conditional schema says which fields an object should have. One field can decide whether another field is needed. Here in this example, the model decides if a response requires escalation via `require_escalation` field, in which case, a `category` is assigned, and when a `category` is classified as `distribution`, a `delivery_method` is also processed. Fields with `when={...}` are required when the condition matches and rejected otherwise.

Conditions can use either the LLM-filled data or values supplied by the application. Runtime conditions check the extracted data. Bind-time conditions check application values before the request is sent. `bind()` applies the bind-time conditions and returns a new model class. That class produces both a short property list for the prompt and a JSON Schema with the same rules for validation or structured output.

## Example: Personalized Response

```python
from main import CSField, ConditionalModel


class CustomerResponseModel(ConditionalModel):
    require_escalation: bool = CSField(alias="escalate")
    message: str = CSField(
        alias="msg",
        description="Write a helpful response for {user_name}.",
    )
    message_localized: str = CSField(
        when_bound=["preferred_language"],
        alias="msg_{preferred_language_code}",
        description="Translate the response for {user_name} into {preferred_language}.",
    )
    category: str = CSField(
        when={"require_escalation": True},
        alias="category",
        enum=["product", "frontend", "backend", "payments", "distribution", "unknown"],
    )
    delivery_method: str = CSField(
        when={"category": "distribution"},
        alias="distribution",
        enum=["delivery", "pickup", "unknown"],
    )

# Normally obtained from your application; hardcoded here for the example.
user_name = "Maya"
preferred_language = "Spanish"
preferred_language_code = "es"

BoundCustomerResponseModel = CustomerResponseModel.bind(
    user_name=user_name,
    preferred_language=preferred_language,
    preferred_language_code=preferred_language_code,
)
```

The application already knows the customer’s name and preferred language. The LLM writes the response and decides whether it needs escalation. If escalation is needed, it chooses a category. Only distribution cases need a delivery method. `bind(**ctx)` fills the personalized descriptions, applies the language condition, and returns a new model class. The Python field names stay the same while the JSON aliases stay short.

```python
propdoc = BoundCustomerResponseModel.propdoc(
    by_alias=True,
    mention_options=True,
    mention_depends=True,
)
# escalate: true or false
# msg: Write a helpful response for Maya.
# msg_es: Translate the response for Maya into Spanish.
# category (Choose one: product, frontend, backend, payments, distribution, unknown) (only if escalate is True)
# distribution (Choose one: delivery, pickup, unknown) (only if category is distribution)

response_schema = BoundCustomerResponseModel.json_schema(
    by_alias=True,
    descriptions=False,
)
# {"anyOf": [{"properties": {...}}, ...], "$defs": {...}}
```

Send the prompt fields and schema separately. After receiving the response,
look up a conditional field by its Python name and use its resolved alias to
read the value:

```python
customer_request = f"Help {user_name} with her order."
completion = client.chat.completions.create(
    model="gpt-agi",
    messages=[
        {
            "role": "system",
            "content": "Analyze the request, decide whether it needs escalation, and draft a response.",
        },
        {
            "role": "user",
            "content": f"Respond in JSON using these fields:\n{propdoc}\n\nRequest: {customer_request}",
        },
    ],
    response_format={
        "type": "json_schema",
        "json_schema": {"name": "customer_response", "schema": response_schema},
    },
)

response = json.loads(completion.choices[0].message.content)
target_key = "message_localized"
response_key = BoundCustomerResponseModel.model_fields[target_key].alias
localized_message = response.get(response_key)  # response.get("msg_es")
```

`response.get(...)` returns `None` when a field is absent from the response.
`BoundCustomerResponseModel.model_validate(response)` validates the response
against the same active branch.

## Features

### Fields that appear only when needed

`CSField(when={"field": value})` makes a field required in the matching branch and forbidden elsewhere. `when_any=[...]` accepts OR condition sets, and `any_of(...)` / `none_of(...)` compare against value sets. Bind-time conditions (`when_truthy`, `when_falsy`, `when_unbound`, `when_bound`) check the `bind()` context instead of request data. Behind the scenes, the library generates one Pydantic model per branch and merges them into a single schema. Controller fields must be finite (`Literal`, `Enum`, `bool`, or an `enum=` list) so every branch can be enumerated. Class creation rejects unknown dependencies, dependency cycles, and ambiguous aliases with a `ValueError`.

### Schemas sized for the job

`json_schema()` emits `anyOf` over the per-branch models. With more than 256 branch combinations it switches to `if`/`then`/`else` rules on a single schema object instead of building a Cartesian product. Two options cut the payload further: `descriptions=False` strips description keys recursively, and `compact=True` moves properties shared by every branch into one `$defs` entry that branches reference. All output follows the JSON Schema specification, so it works with standard validators and structured-output APIs.

### propdoc(): a token-efficient prompt definition

`propdoc()` renders the active properties as a short text list, with options (`mention_options=True`) and conditions (`mention_depends=True`). Nested models appear once below the parent. Paste it into the prompt; pair it with the trimmed schema on the API side.

### Aliases separate code from tokens

`alias=` controls only the name in JSON output. Conditions, templates, and Python code keep using field names, so you can pick short, tokenizer-friendly property names without renaming anything in code. That split keeps the codebase readable while the schema stays cheap to tokenize. `by_alias=True` switches which side appears in `propdoc()` and `json_schema()`.

### Templates filled at bind time

String literal values, `CSField` descriptions, aliases, and enum entries support `{placeholder}` syntax by default. `.bind(**ctx)` fills them from context: `Literal["I will answer in {language}"]` becomes `Literal["I will answer in English"]`, and `description="Reply in {language}"` becomes `"Reply in English"`. Use `CStemplate(...)` for callable templates and dynamic patterns. `CSliteral(key, mapping)` picks a different option list per context value.

### Regex- and prefix-guided generation

`pattern=` puts a regex constraint on a string field, which schema-guided generators can follow during decoding. Plain patterns are static, so regex braces such as `{2,5}` work as written. Use `CStemplate(...)` only when a pattern varies by bind-time context.

RegExp patterns should exclude `"`, `]`, and `}` so a match cannot end the JSON
value early. The library warns when it cannot find this guard. Use a negative
character class such as:

```python
answer: str = CSField(pattern=r'^Answer: [^"\]}]+$')
```

### Object schemas built from runtime data

`CSRecord(data, key_field=..., item_schema=...)` creates an object schema whose property names come from your data instead of static code: each record in a list becomes one property keyed by a chosen field, its alias, or a callable. Inside a model, `CSrecord(...)` does the same at bind time. With `flatten=True`, a one-field item model contributes that field's schema directly, so the output is `{"retries": 3}` rather than `{"retries": {"value": 3}}`.

### CSYesNo

`CSYesNo` is `Literal["yes", "no"]`. LLMs follow patterns. When several
string fields come before a yes/no field, a `"yes"` or `"no"` string can better
align the model's internal pattern with the expected format, especially for
smaller models. In other cases, use `bool`.

```python
require_something: CSYesNo
detail: str = CSField(when={"require_something": "yes"})
```

### Everything else

- Validation dispatch: `model_validate()` and `model_dump()` follow the matched branch.
- Schema caching with defensive copies (`cache=True`); a mutated result never affects later calls.
- Record key extraction by field name, alias, or callable, with clear errors for missing or duplicate keys.
- Legacy names (`CField`, `CRecord`, and friends) remain available through the `compat` module.

## Requirements and setup

Python 3.10+ and Pydantic v2 (`>=2,<3`).

```bash
pip install -e .     # install from this repo
python -m pytest     # run the test suite
```

Full parameter tables and error behavior: [REFERENCE.md](REFERENCE.md).
