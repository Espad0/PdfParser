from datetime import date

import pytest

from bot import _check_global_limit, _daily_counter, _esc, _fmt_num, _format_response, _record_request
from validator import ValidationResult


@pytest.fixture(autouse=True)
def _clear_counter():
    _daily_counter.clear()
    yield
    _daily_counter.clear()


# -- _esc ----------------------------------------------------------------------

class TestEsc:
    def test_none_returns_default_fallback(self):
        assert _esc(None) == "N/A"

    def test_none_custom_fallback(self):
        assert _esc(None, "") == ""

    def test_plain_string(self):
        assert _esc("hello") == "hello"

    def test_html_escaped(self):
        assert _esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"

    def test_ampersand_escaped(self):
        assert _esc("A & B") == "A &amp; B"


# -- _fmt_num ------------------------------------------------------------------

class TestFmtNum:
    def test_none(self):
        assert _fmt_num(None) == "N/A"

    def test_integer(self):
        assert _fmt_num(1000) == "1,000.00"

    def test_float(self):
        assert _fmt_num(1234.56) == "1,234.56"

    def test_string_number(self):
        assert _fmt_num("99.9") == "99.90"

    def test_invalid_returns_escaped(self):
        result = _fmt_num("bad")
        assert "bad" in result


# -- _check_global_limit / _record_request ------------------------------------

class TestGlobalLimit:
    def test_under_limit_returns_none(self):
        assert _check_global_limit() is None

    def test_at_limit_returns_message(self):
        from config import RATE_LIMIT_GLOBAL
        today = date.today().isoformat()
        _daily_counter[today] = RATE_LIMIT_GLOBAL
        assert _check_global_limit() is not None

    def test_prunes_old_entries(self):
        _daily_counter["2020-01-01"] = 999
        _check_global_limit()
        assert "2020-01-01" not in _daily_counter

    def test_record_increments(self):
        today = date.today().isoformat()
        _record_request()
        _record_request()
        assert _daily_counter[today] == 2


# -- _format_response ---------------------------------------------------------

def _make_data(fields_override=None):
    fields = {
        "invoice_number": "INV-001",
        "invoice_date": "2024-01-15",
        "supplier_name": "Acme",
        "supplier_address": "123 St",
        "client_name": "Client",
        "client_address": "456 Ave",
        "supplier_tax_id": "TAX1",
        "client_tax_id": "TAX2",
        "total_excl_vat": 1000.0,
        "total_incl_vat": 1200.0,
        "currency": "EUR",
        "vat_rate": "20%",
        "vat_amount": 200.0,
    }
    if fields_override:
        fields.update(fields_override)
    return {
        "fields": fields,
        "additional_fields": {},
        "line_items": [
            {"description": "Widget", "quantity": 10, "unit_price": 100.0, "unit": "pc", "total": 1000.0},
        ],
    }


class TestFormatResponse:
    def test_contains_invoice_number(self):
        result = _format_response(_make_data(), ValidationResult())
        assert "INV-001" in result

    def test_contains_supplier_and_client(self):
        result = _format_response(_make_data(), ValidationResult())
        assert "Acme" in result
        assert "Client" in result

    def test_html_injection_escaped(self):
        data = _make_data(fields_override={"invoice_number": "<b>evil</b>"})
        result = _format_response(data, ValidationResult())
        assert "<b>evil</b>" not in result
        assert "&lt;b&gt;evil&lt;/b&gt;" in result

    def test_validation_errors_shown(self):
        v = ValidationResult()
        v.add_error("Something broke")
        result = _format_response(_make_data(), v)
        assert "Something broke" in result

    def test_validation_warnings_shown(self):
        v = ValidationResult()
        v.add_warning("Check this")
        result = _format_response(_make_data(), v)
        assert "Check this" in result

    def test_line_items_listed(self):
        result = _format_response(_make_data(), ValidationResult())
        assert "Widget" in result
        assert "Line Items (1)" in result

    def test_additional_fields_shown(self):
        data = _make_data()
        data["additional_fields"] = {"payment_terms": "Net 30"}
        result = _format_response(data, ValidationResult())
        assert "Net 30" in result
