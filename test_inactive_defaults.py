"""Test for fill_inactive functionality."""

import json
from main import CField, ConditionalModel, CYesNo


def test_basic_inactive_with_defaults():
    """Test basic functionality of fill_inactive."""
    print("=" * 60)
    print("Test: Basic inactive fields with defaults")
    print("=" * 60)

    class PetForm(ConditionalModel):
        has_pet: CYesNo
        pet_name: str = CField(when={"has_pet": "yes"})
        pet_age: int = CField(when={"has_pet": "yes"})

    # Without fill_inactive (default behavior - anyOf)
    schema_without = PetForm.json_schema()
    print("Schema WITHOUT fill_inactive:")
    print(json.dumps(schema_without, indent=2))

    # With fill_inactive (new behavior - single schema, no anyOf)
    schema_with = PetForm.json_schema(fill_inactive=True)
    print("\nSchema WITH fill_inactive=True:")
    print(json.dumps(schema_with, indent=2))

    # Verify that fill_inactive eliminates anyOf
    assert "anyOf" in schema_without, "Without fill_inactive should have anyOf"
    assert "anyOf" not in schema_with, "With fill_inactive should NOT have anyOf"

    # Verify control field uses enum
    assert schema_with["properties"]["has_pet"]["enum"] == ["yes", "no"]

    # Verify conditional fields have defaults
    assert schema_with["properties"]["pet_name"]["default"] is None
    assert schema_with["properties"]["pet_age"]["default"] is None

    # Verify only control field is required
    assert schema_with["required"] == ["has_pet"]

    print("\n✓ Inactive fields have null defaults")
    print("✓ No anyOf in schema")
    print("✓ Schema is smaller and simpler")

    print("PASSED\n")


def test_custom_global_default():
    """Test with custom global default value."""
    print("=" * 60)
    print("Test: Custom global default value")
    print("=" * 60)

    class PetForm(ConditionalModel):
        has_pet: CYesNo
        pet_name: str = CField(when={"has_pet": "yes"})
        pet_age: int = CField(when={"has_pet": "yes"})

    # Use empty string as default for inactive fields
    schema = PetForm.json_schema(fill_inactive=True, inactive_default="")
    print("Schema with inactive_default='':")
    print(json.dumps(schema, indent=2))

    # Verify defaults
    assert schema["properties"]["pet_name"]["default"] == ""
    assert schema["properties"]["pet_age"]["default"] == ""
    print("\n✓ Inactive fields have custom default: ''")

    print("PASSED\n")


def test_per_field_defaults():
    """Test with per-field default values."""
    print("=" * 60)
    print("Test: Per-field default values")
    print("=" * 60)

    class PetForm(ConditionalModel):
        has_pet: CYesNo
        pet_name: str = CField(when={"has_pet": "yes"})
        pet_age: int = CField(when={"has_pet": "yes"})

    # Use different defaults for different fields
    schema = PetForm.json_schema(
        fill_inactive=True,
        inactive_default={"pet_name": "No pet", "pet_age": 0}
    )
    print("Schema with per-field defaults:")
    print(json.dumps(schema, indent=2))

    # Verify defaults
    assert schema["properties"]["pet_name"]["default"] == "No pet"
    assert schema["properties"]["pet_age"]["default"] == 0
    print("\n✓ Inactive fields have per-field defaults")

    print("PASSED\n")


def test_field_default_value():
    """Test using field's own default value."""
    print("=" * 60)
    print("Test: Using field's own default value")
    print("=" * 60)

    class PetForm(ConditionalModel):
        has_pet: CYesNo
        pet_name: str = CField(when={"has_pet": "yes"}, default="Unknown")
        pet_age: int = CField(when={"has_pet": "yes"}, default=-1)

    # When inactive_default is None and field has a default, use field's default
    schema = PetForm.json_schema(fill_inactive=True)
    print("Schema using field's own defaults:")
    print(json.dumps(schema, indent=2))

    # Verify defaults
    assert schema["properties"]["pet_name"]["default"] == "Unknown"
    assert schema["properties"]["pet_age"]["default"] == -1
    print("\n✓ Inactive fields use their own defaults")

    print("PASSED\n")


def test_with_aliases():
    """Test with field aliases."""
    print("=" * 60)
    print("Test: With field aliases")
    print("=" * 60)

    class PetForm(ConditionalModel):
        has_pet: CYesNo = CField(alias="hasPet")
        pet_name: str = CField(alias="petName", when={"has_pet": "yes"})
        pet_age: int = CField(alias="petAge", when={"has_pet": "yes"})

    # With by_alias=True
    schema = PetForm.json_schema(by_alias=True, fill_inactive=True)
    print("Schema with by_alias=True and fill_inactive=True:")
    print(json.dumps(schema, indent=2))

    # Verify that aliases are used in schema
    assert "hasPet" in schema["properties"]
    assert "petName" in schema["properties"]
    assert "petAge" in schema["properties"]
    assert schema["properties"]["petName"]["default"] is None
    assert schema["properties"]["petAge"]["default"] is None
    print("\n✓ Inactive fields use aliases correctly")

    print("PASSED\n")


def test_complex_types():
    """Test with complex field types."""
    print("=" * 60)
    print("Test: Complex field types")
    print("=" * 60)

    from typing import List, Optional, Literal

    class Form(ConditionalModel):
        mode: Literal["basic", "advanced"]
        tags: List[str] = CField(when={"mode": "advanced"})
        config: dict = CField(when={"mode": "advanced"})
        optional_field: Optional[str] = CField(when={"mode": "advanced"})

    schema = Form.json_schema(
        fill_inactive=True,
        inactive_default={"tags": [], "config": {}}
    )
    print("Schema with complex types:")
    print(json.dumps(schema, indent=2))

    # Verify complex types
    assert schema["properties"]["tags"]["default"] == []
    assert schema["properties"]["config"]["default"] == {}
    assert schema["properties"]["optional_field"]["default"] is None
    print("\n✓ Complex types handled correctly")

    print("PASSED\n")


def test_bind_exclusion_not_filled():
    """Test that bind-time excluded fields are NOT filled."""
    print("=" * 60)
    print("Test: Bind-time exclusions are not filled")
    print("=" * 60)

    class TestForm(ConditionalModel):
        name: str
        detail: str = CField(when_truthy=["show_detail"])

    # Bind with show_detail=False (excludes 'detail')
    BoundForm = TestForm.bind(show_detail=False)

    schema = BoundForm.json_schema(fill_inactive=True)
    print("Schema after binding with show_detail=False:")
    print(json.dumps(schema, indent=2))

    # Verify detail is NOT in schema (bind-time exclusion respected)
    assert "detail" not in schema.get("properties", {}), \
        "detail should NOT be filled (excluded by bind)"
    print("\n✓ Bind-time exclusions are correctly NOT filled")

    print("PASSED\n")


def test_no_anyof():
    """Test that fill_inactive eliminates anyOf."""
    print("=" * 60)
    print("Test: fill_inactive eliminates anyOf")
    print("=" * 60)

    class Form(ConditionalModel):
        mode: CYesNo
        optional: str = CField(when={"mode": "yes"})

    # Without fill_inactive
    schema_without = Form.json_schema()
    # With fill_inactive
    schema_with = Form.json_schema(fill_inactive=True)

    print("Without fill_inactive:")
    print(f"  Has anyOf: {'anyOf' in schema_without}")
    print(f"  Size: {len(json.dumps(schema_without))} chars")

    print("\nWith fill_inactive:")
    print(f"  Has anyOf: {'anyOf' in schema_with}")
    print(f"  Size: {len(json.dumps(schema_with))} chars")

    assert "anyOf" in schema_without
    assert "anyOf" not in schema_with

    reduction = len(json.dumps(schema_without)) - len(json.dumps(schema_with))
    print(f"\nSize reduction: {reduction} chars ({reduction/len(json.dumps(schema_without))*100:.1f}%)")
    print("✓ fill_inactive eliminates anyOf and reduces schema size")

    print("PASSED\n")


def run_all_tests():
    """Run all tests."""
    test_basic_inactive_with_defaults()
    test_custom_global_default()
    test_per_field_defaults()
    test_field_default_value()
    test_with_aliases()
    test_complex_types()
    test_bind_exclusion_not_filled()
    test_no_anyof()

    print("=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
