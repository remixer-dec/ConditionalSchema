"""Tests for CRecord functionality."""

from pydantic import BaseModel, Field
from main import (
    CRecord,
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
    record = CRecord(
        data=old_armor_list,
        key_field="armor_item_name",
        item_schema=UpdatableArmorItemModel,
    )

    # Check keys
    assert record.keys == ["helmet", "chestplate", "boots"]

    # Check data_map
    assert "helmet" in record.data_map
    assert record.data_map["helmet"]["defense"] == 10

    # Check schema
    schema = record.json_schema()
    assert schema["type"] == "object"
    assert "helmet" in schema["properties"]
    assert "chestplate" in schema["properties"]
    assert "boots" in schema["properties"]
    assert set(schema["required"]) == {"helmet", "chestplate", "boots"}


def test_crecord_dict_input():
    """Test CRecord with dict of dicts input."""
    record = CRecord(
        data=old_armor_dict,
        key_field="armor_item_name",  # Not used for dict input
        item_schema=UpdatableArmorItemModel,
    )

    # Check keys (from dict keys directly)
    assert set(record.keys) == {"helmet", "chestplate", "boots"}

    # Check schema
    schema = record.json_schema()
    assert "helmet" in schema["properties"]


def test_crecord_with_alias():
    """Test CRecord with alias-based key extraction."""
    record = CRecord(
        data=old_armor_with_alias,
        key_field="armor_item_name",
        item_schema=ArmorItemModel,
        use_alias=True,  # Use alias "armorItemName" to look up values
    )

    assert record.keys == ["helmet", "chestplate"]

    assert record.data_map["helmet"]["armorItemName"] == "helmet"


def test_crecord_with_callable():
    """Test CRecord with callable key extraction."""
    record = CRecord(
        data=old_armor_list,
        key_field=lambda item: f"item_{item['armor_item_name'].upper()}",
        item_schema=UpdatableArmorItemModel,
    )

    assert record.keys == ["item_HELMET", "item_CHESTPLATE", "item_BOOTS"]

    schema = record.json_schema()
    assert "item_HELMET" in schema["properties"]


def test_crecord_optional_properties():
    """Test CRecord with optional (not required) properties."""
    record = CRecord(
        data=old_armor_list,
        key_field="armor_item_name",
        item_schema=UpdatableArmorItemModel,
        required=False,
    )

    schema = record.json_schema()
    assert "required" not in schema or schema.get("required") == []


def test_crecord_model_generation():
    """Test CRecord model generation."""
    record = CRecord(
        data=old_armor_list,
        key_field="armor_item_name",
        item_schema=UpdatableArmorItemModel,
    )

    model = record.model()
    assert model.__name__ == "DynamicRecord"
    assert "helmet" in model.model_fields
    assert "chestplate" in model.model_fields


def test_crecord_template_binding():
    """Test CRecord template binding through ConditionalModel."""

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

    # Check the armor_updates field is properly generated
    variants = BoundForm._get_variants()
    assert len(variants) == 1

    # The variant should have the armor_updates field with dynamic properties
    variant = variants[0]
    assert "armor_updates" in variant.model_fields
    assert "armor_updates" in schema["properties"]


def test_crecord_template_without_data():
    """Test CRecordTemplate when data is not in context."""

    class UpdateArmorForm(ConditionalModel):
        action: str
        armor_updates: dict = CField(
            Crecord("armor_data", "armor_item_name", UpdatableArmorItemModel),
            when_truthy=["armor_data"],
        )

    # Bind without armor_data - field should be excluded
    BoundForm = UpdateArmorForm.bind(other_key="value")

    schema = BoundForm.json_schema()

    # armor_updates should NOT be in the schema
    assert "armor_updates" not in schema.get("properties", {})


def test_crecord_by_alias_schema():
    """Test CRecord schema generation with by_alias."""

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

    # With alias
    schema_with_alias = record.json_schema(by_alias=True)

    # Check that item schema reflects alias setting
    sword_schema_no_alias = schema_no_alias["$defs"]["CRecordItem"]
    sword_schema_with_alias = schema_with_alias["$defs"]["CRecordItem"]

    assert sword_schema_no_alias["properties"]["item_name"]["type"] == "string"
    assert sword_schema_with_alias["properties"]["itemName"]["type"] == "string"
    assert sword_schema_with_alias["required"] == ["itemName", "itemValue"]


def test_crecord_repr():
    """Test CRecord and Crecord string representation."""
    record = CRecord(
        data=old_armor_list,
        key_field="armor_item_name",
        item_schema=UpdatableArmorItemModel,
    )
    template = Crecord("armor_data", "armor_item_name", UpdatableArmorItemModel)
    assert repr(record).startswith("CRecord(")
    assert repr(template).startswith("Crecord(")
