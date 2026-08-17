"""Compatibility aliases for the pre-CS public names."""

from main import (
    CSField,
    CSRecord,
    CSRecordTemplate,
    CSYesNo,
    CSliteral,
    CSrecord,
    CStemplate,
)

CField = CSField
CRecord = CSRecord
CRecordTemplate = CSRecordTemplate
CYesNo = CSYesNo
Cliteral = CSliteral
Crecord = CSrecord
Ctemplate = CStemplate
c_field = CSField
c_literal = CSliteral
c_record = CSrecord
c_template = CStemplate

__all__ = [
    "CField",
    "CRecord",
    "CRecordTemplate",
    "CYesNo",
    "Cliteral",
    "Crecord",
    "Ctemplate",
    "c_field",
    "c_literal",
    "c_record",
    "c_template",
]
