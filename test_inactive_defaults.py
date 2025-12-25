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

    # Without fill_inactive (default behavior)
    schema_without = PetForm.json_schema()
    print("Schema WITHOUT fill_inactive:")
    print(json.dumps(schema_without, indent=2))

    # With fill_inactive (new behavior)
    schema_with = PetForm.json_schema(fill_inactive=True)
    print("\nSchema WITH fill_inactive=True:")
    print(json.dumps(schema_with, indent=2))

    # Verify that inactive fields are included with null defaults
    for variant in schema_with["anyOf"]:
        props = variant.get("properties", {})
        if props.get("has_pet", {}).get("enum") == ["no"]:
            # When has_pet=no, pet_name and pet_age should have defaults
            assert "pet_name" in props, "pet_name should be in schema"
            assert "pet_age" in props, "pet_age should be in schema"
            assert props["pet_name"]["default"] is None, "pet_name default should be None"
            assert props["pet_age"]["default"] is None, "pet_age default should be None"
            print("\n✓ Inactive fields have null defaults")

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
    schema = PetForm.json_schema(
        fill_inactive=True,
        inactive_default=""
    )
    print("Schema with inactive_default='':")
    print(json.dumps(schema, indent=2))

    # Verify defaults
    for variant in schema["anyOf"]:
        props = variant.get("properties", {})
        if props.get("has_pet", {}).get("enum") == ["no"]:
            assert props["pet_name"]["default"] == "", "Default should be empty string"
            assert props["pet_age"]["default"] == "", "Default should be empty string"
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
        inactive_default={
            "pet_name": "No pet",
            "pet_age": 0
        }
    )
    print("Schema with per-field defaults:")
    print(json.dumps(schema, indent=2))

    # Verify defaults
    for variant in schema["anyOf"]:
        props = variant.get("properties", {})
        if props.get("has_pet", {}).get("enum") == ["no"]:
            assert props["pet_name"]["default"] == "No pet"
            assert props["pet_age"]["default"] == 0
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
    for variant in schema["anyOf"]:
        props = variant.get("properties", {})
        if props.get("has_pet", {}).get("enum") == ["no"]:
            assert props["pet_name"]["default"] == "Unknown"
            assert props["pet_age"]["default"] == -1
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
    schema = PetForm.json_schema(
        by_alias=True,
        fill_inactive=True
    )
    print("Schema with by_alias=True and fill_inactive=True:")
    print(json.dumps(schema, indent=2))

    # Verify that aliases are used in schema
    for variant in schema["anyOf"]:
        props = variant.get("properties", {})
        if props.get("hasPet", {}).get("enum") == ["no"]:
            assert "petName" in props, "Should use alias petName"
            assert "petAge" in props, "Should use alias petAge"
            assert props["petName"]["default"] is None
            assert props["petAge"]["default"] is None
            print("\n✓ Inactive fields use aliases correctly")

    print("PASSED\n")


def test_complex_types():
    """Test with complex field types."""
    print("=" * 60)
    print("Test: Complex field types")
    print("=" * 60)

    from typing import List, Optional

    class Form(ConditionalModel):
        mode: str
        tags: List[str] = CField(when={"mode": "advanced"})
        config: dict = CField(when={"mode": "advanced"})
        optional_field: Optional[str] = CField(when={"mode": "advanced"})

    schema = Form.json_schema(
        fill_inactive=True,
        inactive_default={
            "tags": [],
            "config": {},
        }
    )
    print("Schema with complex types:")
    print(json.dumps(schema, indent=2))

    # Find the variant where mode != "advanced"
    for variant in schema.get("anyOf", [schema]):
        props = variant.get("properties", {})
        # Check if this variant has the inactive fields
        if "tags" in props and "default" in props["tags"]:
            assert props["tags"]["default"] == []
            assert props["config"]["default"] == {}
            assert props["optional_field"]["default"] is None
            print("\n✓ Complex types handled correctly")
            break

    print("PASSED\n")


def test_single_variant_model():
    """Test with a model that has only one variant."""
    print("=" * 60)
    print("Test: Single variant model with runtime condition")
    print("=" * 60)

    from typing import Literal

    class SimpleForm(ConditionalModel):
        mode: Literal["simple", "detailed"]
        description: str = CField(when={"mode": "detailed"})

    schema = SimpleForm.json_schema(fill_inactive=True)
    print("Schema for single variant with inactive field:")
    print(json.dumps(schema, indent=2))

    # Find the variant where mode="simple"
    for variant in schema.get("anyOf", [schema]):
        props = variant.get("properties", {})
        if props.get("mode", {}).get("const") == "simple":
            # Verify description field is included with default
            assert "description" in props, "description should be filled"
            assert props["description"]["default"] is None
            print("\n✓ Runtime-excluded field filled with default")
            break

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


def run_all_tests():
    """Run all tests."""
    test_basic_inactive_with_defaults()
    test_custom_global_default()
    test_per_field_defaults()
    test_field_default_value()
    test_with_aliases()
    test_complex_types()
    test_single_variant_model()
    test_bind_exclusion_not_filled()

    print("=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
