"""Validation logic for extracted invoice data."""

from dataclasses import dataclass, field

REQUIRED_FIELDS = [
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "supplier_address",
    "client_name",
    "client_address",
    "supplier_tax_id",
    "client_tax_id",
    "total_excl_vat",
    "total_incl_vat",
]

NUMERIC_FIELDS = ["total_excl_vat", "total_incl_vat", "vat_amount"]

# Relative tolerance for cross-validation of totals (2% to account for rounding)
TOLERANCE = 0.02


@dataclass
class ValidationResult:
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate(data: dict) -> ValidationResult:
    """Validate extracted invoice data for completeness and consistency.

    Checks:
        1. All 10 required fields are present and non-null.
        2. Numeric fields contain valid numbers.
        3. total_excl_vat + vat_amount ≈ total_incl_vat.
        4. Sum of line item totals ≈ total_excl_vat.
        5. Each line item has description, quantity, and total.
    """
    result = ValidationResult()
    fields = data.get("fields", {})
    line_items = data.get("line_items", [])

    # 1. Required field presence
    for fname in REQUIRED_FIELDS:
        if fields.get(fname) is None:
            result.add_warning(f"Field '{fname}' was not found in the document.")

    # 2. Numeric fields are valid numbers
    for fname in NUMERIC_FIELDS:
        val = fields.get(fname)
        if val is not None and _safe_float(val) is None:
            result.add_error(f"Field '{fname}' has non-numeric value: {val}")

    # 3. VAT cross-check: total_excl_vat + vat_amount ≈ total_incl_vat
    excl = _safe_float(fields.get("total_excl_vat"))
    incl = _safe_float(fields.get("total_incl_vat"))
    vat = _safe_float(fields.get("vat_amount"))

    if excl is not None and incl is not None and vat is not None:
        expected_incl = excl + vat
        if incl > 0 and abs(expected_incl - incl) / incl > TOLERANCE:
            result.add_warning(
                f"VAT cross-check: {excl} + {vat} = {expected_incl}, "
                f"but total_incl_vat = {incl}"
            )

    # 4. Line-item sum vs total_excl_vat
    if excl is not None and line_items:
        items_sum = sum(_safe_float(item.get("total")) or 0 for item in line_items)
        if excl > 0 and abs(items_sum - excl) / excl > TOLERANCE:
            result.add_warning(
                f"Line item sum ({items_sum:.2f}) differs from "
                f"total_excl_vat ({excl:.2f})."
            )

    # 5. Line item completeness
    for i, item in enumerate(line_items, 1):
        if not item.get("description"):
            result.add_warning(f"Line item {i}: missing description.")
        if item.get("quantity") is None:
            result.add_warning(f"Line item {i}: missing quantity.")
        if item.get("total") is None:
            result.add_warning(f"Line item {i}: missing total.")

    return result
