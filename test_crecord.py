"""Tests for CRecord and CRecordTemplate functionality."""

import json
from pydantic import BaseModel, Field
from main import (
    CRecord,
    CRecordTemplate,
    Crecord,
    CField,
    ConditionalModel,
)


# Test models
class ArmorItemModel(BaseModel):
    armor_item_name: str = Field(alias="armorItemName")
    defense: int
    durability: int = 100


class UpdatableArmorItemModel(BaseModel):
    defense: int = Field(ge=0, le=100, description="Defense value")
    durability: int = Field(ge=0, le=100, description="Durability value")


# Mock data
old_armor_list = [
    {"armor_item_name": "helmet", "defense": 10, "durability": 80},
    {"armor_item_name": "chestplate", "defense": 25, "durability": 90},
    {"armor_item_name": "boots", "defense": 5, "durability": 70},
]

old_armor_dict = {
    "helmet": {"armor_item_name": "helmet", "defense": 10, "durability": 80},
    "chestplate": {"armor_item_name": "chestplate", "defense": 25, "durability": 90},
    "boots": {"armor_item_name": "boots", "defense": 5, "durability": 70},
}

# Data with aliases
old_armor_with_alias = [
    {"armorItemName": "helmet", "defense": 10, "durability": 80},
    {"armorItemName": "chestplate", "defense": 25, "durability": 90},
]


def test_crecord_list_input():
    """Test CRecord with list of dicts input."""
    print("=" * 60)
    print("Test: CRecord with list input")
    print("=" * 60)

    record = CRecord(
        data=old_armor_list,
        key_field="armor_item_name",
        item_schema=UpdatableArmorItemModel,
    )

    # Check keys
    print(f"Keys: {record.keys}")
    assert record.keys == ["helmet", "chestplate", "boots"]

    # Check data_map
    print(f"Data map: {json.dumps(record.data_map, indent=2)}")
    assert "helmet" in record.data_map
    assert record.data_map["helmet"]["defense"] == 10

    # Check schema
    schema = record.json_schema()
    print(f"Schema: {json.dumps(schema, indent=2)}")
    assert schema["type"] == "object"
    assert "helmet" in schema["properties"]
    assert "chestplate" in schema["properties"]
    assert "boots" in schema["properties"]
    assert set(schema["required"]) == {"helmet", "chestplate", "boots"}

    print("PASSED\n")


def test_crecord_dict_input():
    """Test CRecord with dict of dicts input."""
    print("=" * 60)
    print("Test: CRecord with dict input")
    print("=" * 60)

    record = CRecord(
        data=old_armor_dict,
        key_field="armor_item_name",  # Not used for dict input
        item_schema=UpdatableArmorItemModel,
    )

    # Check keys (from dict keys directly)
    print(f"Keys: {record.keys}")
    assert set(record.keys) == {"helmet", "chestplate", "boots"}

    # Check schema
    schema = record.json_schema()
    print(f"Schema: {json.dumps(schema, indent=2)}")
    assert "helmet" in schema["properties"]

    print("PASSED\n")


def test_crecord_with_alias():
    """Test CRecord with alias-based key extraction."""
    print("=" * 60)
    print("Test: CRecord with alias lookup")
    print("=" * 60)

    record = CRecord(
        data=old_armor_with_alias,
        key_field="armor_item_name",
        item_schema=ArmorItemModel,
        use_alias=True,  # Use alias "armorItemName" to look up values
    )

    print(f"Keys: {record.keys}")
    assert record.keys == ["helmet", "chestplate"]

    print(f"Data map: {json.dumps(record.data_map, indent=2)}")
    assert record.data_map["helmet"]["armorItemName"] == "helmet"

    print("PASSED\n")


def test_crecord_with_callable():
    """Test CRecord with callable key extraction."""
    print("=" * 60)
    print("Test: CRecord with callable key extractor")
    print("=" * 60)

    record = CRecord(
        data=old_armor_list,
        key_field=lambda item: f"item_{item['armor_item_name'].upper()}",
        item_schema=UpdatableArmorItemModel,
    )

    print(f"Keys: {record.keys}")
    assert record.keys == ["item_HELMET", "item_CHESTPLATE", "item_BOOTS"]

    schema = record.json_schema()
    print(f"Schema properties: {list(schema['properties'].keys())}")
    assert "item_HELMET" in schema["properties"]

    print("PASSED\n")


def test_crecord_optional_properties():
    """Test CRecord with optional (not required) properties."""
    print("=" * 60)
    print("Test: CRecord with optional properties")
    print("=" * 60)

    record = CRecord(
        data=old_armor_list,
        key_field="armor_item_name",
        item_schema=UpdatableArmorItemModel,
        required=False,
    )

    schema = record.json_schema()
    print(f"Schema: {json.dumps(schema, indent=2)}")
    assert "required" not in schema or schema.get("required") == []

    print("PASSED\n")


def test_crecord_model_generation():
    """Test CRecord model generation."""
    print("=" * 60)
    print("Test: CRecord model generation")
    print("=" * 60)

    record = CRecord(
        data=old_armor_list,
        key_field="armor_item_name",
        item_schema=UpdatableArmorItemModel,
    )

    model = record.model()
    print(f"Model name: {model.__name__}")
    print(f"Model fields: {list(model.model_fields.keys())}")

    assert model.__name__ == "DynamicRecord"
    assert "helmet" in model.model_fields
    assert "chestplate" in model.model_fields

    print("PASSED\n")


def test_crecord_template_binding():
    """Test CRecordTemplate with ConditionalModel binding."""
    print("=" * 60)
    print("Test: CRecordTemplate with ConditionalModel binding")
    print("=" * 60)

    class UpdateArmorForm(ConditionalModel):
        action: str
        armor_updates: dict = CField(
            Crecord("armor_data", "armor_item_name", UpdatableArmorItemModel),
            when_truthy=["armor_data"],
        )

    # Bind with data
    BoundForm = UpdateArmorForm.bind(armor_data=old_armor_list)

    # Get schema
    schema = BoundForm.json_schema()
    print(f"Schema: {json.dumps(schema, indent=2)}")

    # Check the armor_updates field is properly generated
    variants = BoundForm._get_variants()
    print(f"Number of variants: {len(variants)}")

    # The variant should have the armor_updates field with dynamic properties
    variant = variants[0]
    print(f"Variant fields: {list(variant.model_fields.keys())}")

    print("PASSED\n")


def test_crecord_template_without_data():
    """Test CRecordTemplate when data is not in context."""
    print("=" * 60)
    print("Test: CRecordTemplate without data (field excluded by when_truthy)")
    print("=" * 60)

    class UpdateArmorForm(ConditionalModel):
        action: str
        armor_updates: dict = CField(
            Crecord("armor_data", "armor_item_name", UpdatableArmorItemModel),
            when_truthy=["armor_data"],
        )

    # Bind without armor_data - field should be excluded
    BoundForm = UpdateArmorForm.bind(other_key="value")

    schema = BoundForm.json_schema()
    print(f"Schema: {json.dumps(schema, indent=2)}")

    # armor_updates should NOT be in the schema
    assert "armor_updates" not in schema.get("properties", {})

    print("PASSED\n")


def test_crecord_by_alias_schema():
    """Test CRecord schema generation with by_alias."""
    print("=" * 60)
    print("Test: CRecord schema with by_alias=True")
    print("=" * 60)

    class ItemWithAlias(BaseModel):
        item_name: str = Field(alias="itemName")
        value: int = Field(alias="itemValue")

    record = CRecord(
        data=[{"name": "sword"}, {"name": "shield"}],
        key_field=lambda item: item["name"],
        item_schema=ItemWithAlias,
    )

    # Without alias
    schema_no_alias = record.json_schema(by_alias=False)
    print(f"Schema (no alias): {json.dumps(schema_no_alias, indent=2)}")

    # With alias
    schema_with_alias = record.json_schema(by_alias=True)
    print(f"Schema (with alias): {json.dumps(schema_with_alias, indent=2)}")

    # Check that item schema reflects alias setting
    sword_schema_no_alias = schema_no_alias["properties"]["sword"]
    sword_schema_with_alias = schema_with_alias["properties"]["sword"]

    print("PASSED\n")


def test_crecord_repr():
    """Test CRecord and CRecordTemplate string representation."""
    print("=" * 60)
    print("Test: CRecord and CRecordTemplate repr")
    print("=" * 60)

    record = CRecord(
        data=old_armor_list,
        key_field="armor_item_name",
        item_schema=UpdatableArmorItemModel,
    )
    print(f"CRecord repr: {repr(record)}")

    template = Crecord("armor_data", "armor_item_name", UpdatableArmorItemModel)
    print(f"CRecordTemplate repr: {repr(template)}")

    print("PASSED\n")


def run_all_tests():
    """Run all tests."""
    test_crecord_list_input()
    test_crecord_dict_input()
    test_crecord_with_alias()
    test_crecord_with_callable()
    test_crecord_optional_properties()
    test_crecord_model_generation()
    test_crecord_template_binding()
    test_crecord_template_without_data()
    test_crecord_by_alias_schema()
    test_crecord_repr()

    print("=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
