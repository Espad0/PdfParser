from validator import validate, _safe_float


def _make_data(fields=None, line_items=None):
    defaults = {
        "invoice_number": "INV-001",
        "invoice_date": "2024-01-15",
        "supplier_name": "Acme Corp",
        "supplier_address": "123 Main St",
        "client_name": "Client Inc",
        "client_address": "456 Oak Ave",
        "supplier_tax_id": "DE123456789",
        "client_tax_id": "FR987654321",
        "total_excl_vat": 1000.0,
        "total_incl_vat": 1200.0,
        "currency": "EUR",
        "vat_rate": "20%",
        "vat_amount": 200.0,
    }
    if fields:
        defaults.update(fields)
    return {
        "fields": defaults,
        "line_items": line_items if line_items is not None else [
            {"description": "Widget", "quantity": 10, "unit_price": 100.0, "unit": "pc", "total": 1000.0},
        ],
    }


class TestSafeFloat:
    def test_none(self):
        assert _safe_float(None) is None

    def test_int(self):
        assert _safe_float(42) == 42.0

    def test_float(self):
        assert _safe_float(3.14) == 3.14

    def test_numeric_string(self):
        assert _safe_float("100.5") == 100.5

    def test_invalid_string(self):
        assert _safe_float("abc") is None

    def test_empty_string(self):
        assert _safe_float("") is None


class TestValidateRequiredFields:
    def test_all_present_no_warnings(self):
        result = validate(_make_data())
        assert result.is_valid
        assert result.errors == []
        assert result.warnings == []

    def test_single_missing_field(self):
        result = validate(_make_data(fields={"invoice_number": None}))
        assert any("invoice_number" in w for w in result.warnings)

    def test_multiple_missing_fields(self):
        result = validate(_make_data(fields={"invoice_number": None, "supplier_name": None}))
        missing = [w for w in result.warnings if "was not found" in w]
        assert len(missing) == 2

    def test_all_required_missing(self):
        result = validate({"fields": {}, "line_items": []})
        missing = [w for w in result.warnings if "was not found" in w]
        assert len(missing) == 10

    def test_empty_data_dict(self):
        result = validate({})
        missing = [w for w in result.warnings if "was not found" in w]
        assert len(missing) == 10


class TestValidateNumericFields:
    def test_valid_numbers_no_errors(self):
        result = validate(_make_data())
        assert not any("non-numeric" in e for e in result.errors)

    def test_non_numeric_total(self):
        result = validate(_make_data(fields={"total_excl_vat": "abc"}))
        assert not result.is_valid
        assert any("total_excl_vat" in e and "non-numeric" in e for e in result.errors)

    def test_non_numeric_vat_amount(self):
        result = validate(_make_data(fields={"vat_amount": "xyz"}))
        assert not result.is_valid
        assert any("vat_amount" in e for e in result.errors)

    def test_null_numeric_not_flagged(self):
        result = validate(_make_data(fields={"vat_amount": None}))
        assert not any("non-numeric" in e for e in result.errors)


class TestValidateVATCrossCheck:
    def test_correct_vat(self):
        data = _make_data(fields={
            "total_excl_vat": 1000.0, "vat_amount": 200.0, "total_incl_vat": 1200.0,
        })
        result = validate(data)
        assert not any("VAT cross-check" in w for w in result.warnings)

    def test_incorrect_vat(self):
        data = _make_data(fields={
            "total_excl_vat": 1000.0, "vat_amount": 200.0, "total_incl_vat": 1500.0,
        })
        result = validate(data)
        assert any("VAT cross-check" in w for w in result.warnings)

    def test_within_tolerance(self):
        # ~1% off: abs(1200-1212)/1212 ≈ 0.99% < 2% tolerance → no warning
        data = _make_data(fields={
            "total_excl_vat": 1000.0, "vat_amount": 200.0, "total_incl_vat": 1212.0,
        })
        result = validate(data)
        assert not any("VAT cross-check" in w for w in result.warnings)

    def test_skipped_when_vat_missing(self):
        result = validate(_make_data(fields={"vat_amount": None}))
        assert not any("VAT cross-check" in w for w in result.warnings)

    def test_skipped_when_excl_missing(self):
        result = validate(_make_data(fields={"total_excl_vat": None}))
        assert not any("VAT cross-check" in w for w in result.warnings)


class TestValidateLineItemSum:
    def test_sum_matches(self):
        data = _make_data(
            fields={"total_excl_vat": 300.0},
            line_items=[
                {"description": "A", "quantity": 1, "total": 100.0},
                {"description": "B", "quantity": 2, "total": 200.0},
            ],
        )
        result = validate(data)
        assert not any("Line item sum" in w for w in result.warnings)

    def test_sum_differs(self):
        data = _make_data(
            fields={"total_excl_vat": 500.0},
            line_items=[{"description": "A", "quantity": 1, "total": 100.0}],
        )
        result = validate(data)
        assert any("Line item sum" in w for w in result.warnings)

    def test_no_items_skips_check(self):
        result = validate(_make_data(line_items=[]))
        assert not any("Line item sum" in w for w in result.warnings)

    def test_null_excl_skips_check(self):
        data = _make_data(
            fields={"total_excl_vat": None},
            line_items=[{"description": "A", "quantity": 1, "total": 100.0}],
        )
        result = validate(data)
        assert not any("Line item sum" in w for w in result.warnings)


class TestValidateLineItems:
    def test_complete_item_no_warnings(self):
        data = _make_data(
            fields={"total_excl_vat": 50.0},
            line_items=[{"description": "Widget", "quantity": 5, "total": 50.0}],
        )
        result = validate(data)
        assert not any("missing" in w for w in result.warnings)

    def test_missing_description(self):
        data = _make_data(line_items=[{"quantity": 1, "total": 10.0}])
        result = validate(data)
        assert any("missing description" in w for w in result.warnings)

    def test_missing_quantity(self):
        data = _make_data(line_items=[{"description": "X", "total": 10.0}])
        result = validate(data)
        assert any("missing quantity" in w for w in result.warnings)

    def test_missing_total(self):
        data = _make_data(line_items=[{"description": "X", "quantity": 1}])
        result = validate(data)
        assert any("missing total" in w for w in result.warnings)
