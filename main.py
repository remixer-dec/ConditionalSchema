"""Backward-compatible public API for Conditional Schema.

Implementation details live in focused modules. Existing applications can
continue importing the original names from ``main``.
"""

import model as _model

AnyOf = _model.AnyOf
CField = _model.CField
CRecord = _model.CRecord
CRecordTemplate = _model.CRecordTemplate
Ctemplate = _model.Ctemplate
Cliteral = _model.Cliteral
ConditionalFieldInfo = _model.ConditionalFieldInfo
ConditionalModel = _model.ConditionalModel
Crecord = _model.Crecord
FALSY = _model.FALSY
LiteralTemplate = _model.LiteralTemplate
NoneOf = _model.NoneOf
Template = _model.Template
TRUTHY = _model.TRUTHY
UNBOUND = _model.UNBOUND
any_of = _model.any_of
none_of = _model.none_of
truthy = _model.truthy

_build_compact_schema = _model._build_compact_schema
_cache_schema_result = _model._cache_schema_result
_common_schema_properties = _model._common_schema_properties
_generate_combos = _model._generate_combos
_merge_variant_schema_definitions = _model._merge_variant_schema_definitions
_schema_fingerprint = _model._schema_fingerprint
_strip_descriptions = _model._strip_descriptions

c_template = Ctemplate
c_literal = Cliteral
c_record = Crecord
c_field = CField

__all__ = list(_model.__all__) + ["c_template", "c_literal", "c_record", "c_field"]
