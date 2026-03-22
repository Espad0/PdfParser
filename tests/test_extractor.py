import json
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from extractor import _sanitize_output, _sanitize_value, extract_invoice_data


# -- _sanitize_value ----------------------------------------------------------

class TestSanitizeValue:
    def test_none_passthrough(self):
        assert _sanitize_value(None) is None

    def test_int_to_float(self):
        assert _sanitize_value(42) == 42.0

    def test_float_passthrough(self):
        assert _sanitize_value(3.14) == 3.14

    def test_bool_treated_as_string(self):
        assert _sanitize_value(True) == "True"

    def test_string_passthrough(self):
        assert _sanitize_value("hello") == "hello"

    def test_long_string_truncated(self):
        long = "x" * 600
        assert len(_sanitize_value(long)) == 500


# -- _sanitize_output ---------------------------------------------------------

def _make_raw(fields=None, line_items=None, additional_fields=None):
    return {
        "fields": fields or {},
        "line_items": line_items or [],
        "additional_fields": additional_fields or {},
    }


class TestSanitizeOutputFields:
    def test_valid_fields_pass_through(self):
        raw = _make_raw(fields={
            "invoice_number": "INV-1",
            "total_excl_vat": 100.0,
        })
        result = _sanitize_output(raw)
        assert result["fields"]["invoice_number"] == "INV-1"
        assert result["fields"]["total_excl_vat"] == 100.0

    def test_extra_keys_stripped(self):
        raw = _make_raw(fields={"invoice_number": "INV-1", "evil_key": "hack"})
        result = _sanitize_output(raw)
        assert "evil_key" not in result["fields"]

    def test_numeric_string_coerced(self):
        raw = _make_raw(fields={"total_excl_vat": "123.45"})
        result = _sanitize_output(raw)
        assert result["fields"]["total_excl_vat"] == 123.45

    def test_invalid_numeric_becomes_none(self):
        raw = _make_raw(fields={"total_excl_vat": "not a number"})
        result = _sanitize_output(raw)
        assert result["fields"]["total_excl_vat"] is None

    def test_string_truncated(self):
        raw = _make_raw(fields={"invoice_number": "x" * 600})
        result = _sanitize_output(raw)
        assert len(result["fields"]["invoice_number"]) == 500

    def test_non_dict_fields_handled(self):
        result = _sanitize_output({"fields": "bad", "line_items": [], "additional_fields": {}})
        assert result["fields"]["invoice_number"] is None

    def test_missing_field_defaults_to_none(self):
        result = _sanitize_output(_make_raw())
        assert result["fields"]["invoice_number"] is None
        assert result["fields"]["total_excl_vat"] is None


class TestSanitizeOutputLineItems:
    def test_valid_items(self):
        raw = _make_raw(line_items=[
            {"description": "Widget", "quantity": 5, "unit_price": 10.0, "unit": "pc", "total": 50.0},
        ])
        result = _sanitize_output(raw)
        assert len(result["line_items"]) == 1
        assert result["line_items"][0]["description"] == "Widget"
        assert result["line_items"][0]["quantity"] == 5.0

    def test_non_list_items_handled(self):
        result = _sanitize_output({"fields": {}, "line_items": "bad", "additional_fields": {}})
        assert result["line_items"] == []

    def test_non_dict_item_skipped(self):
        raw = _make_raw(line_items=["not a dict", {"description": "OK", "quantity": 1, "total": 10.0}])
        result = _sanitize_output(raw)
        assert len(result["line_items"]) == 1

    def test_extra_item_keys_allowed(self):
        raw = _make_raw(line_items=[
            {"description": "X", "quantity": 1, "total": 10.0, "item_code": "ABC"},
        ])
        result = _sanitize_output(raw)
        assert result["line_items"][0]["item_code"] == "ABC"

    def test_invalid_identifier_extra_key_rejected(self):
        raw = _make_raw(line_items=[
            {"description": "X", "quantity": 1, "total": 10.0, "not-valid": "val"},
        ])
        result = _sanitize_output(raw)
        assert "not-valid" not in result["line_items"][0]

    def test_max_extra_keys_enforced(self):
        extras = {f"extra_{i}": i for i in range(15)}
        item = {"description": "X", "quantity": 1, "total": 10.0, **extras}
        raw = _make_raw(line_items=[item])
        result = _sanitize_output(raw)
        extra_keys = [k for k in result["line_items"][0] if k.startswith("extra_")]
        assert len(extra_keys) == 10


class TestSanitizeOutputAdditionalFields:
    def test_valid_additional_fields(self):
        raw = _make_raw(additional_fields={"payment_terms": "Net 30"})
        result = _sanitize_output(raw)
        assert result["additional_fields"]["payment_terms"] == "Net 30"

    def test_invalid_key_rejected(self):
        raw = _make_raw(additional_fields={"not-valid": "val"})
        result = _sanitize_output(raw)
        assert "not-valid" not in result["additional_fields"]

    def test_non_dict_handled(self):
        result = _sanitize_output({"fields": {}, "line_items": [], "additional_fields": "bad"})
        assert result["additional_fields"] == {}

    def test_max_fields_enforced(self):
        many = {f"field_{i}": f"val_{i}" for i in range(25)}
        raw = _make_raw(additional_fields=many)
        result = _sanitize_output(raw)
        assert len(result["additional_fields"]) == 20


# -- extract_invoice_data (mocked API) ----------------------------------------

def _mock_response(text, stop_reason="end_turn"):
    response = MagicMock()
    response.stop_reason = stop_reason
    response.content = [MagicMock(text=text)]
    return response


class TestExtractInvoiceData:
    @patch("extractor._client")
    def test_valid_json_parsed(self, mock_client):
        payload = json.dumps({
            "fields": {"invoice_number": "INV-1"},
            "line_items": [{"description": "X", "quantity": 1, "total": 10.0}],
        })
        mock_client.messages.create.return_value = _mock_response(payload)
        result = extract_invoice_data(b"fake", "image/jpeg")
        assert result["fields"]["invoice_number"] == "INV-1"

    @patch("extractor._client")
    def test_markdown_fences_stripped(self, mock_client):
        payload = json.dumps({"fields": {}, "line_items": []})
        wrapped = f"```json\n{payload}\n```"
        mock_client.messages.create.return_value = _mock_response(wrapped)
        result = extract_invoice_data(b"fake", "image/jpeg")
        assert "fields" in result

    @patch("extractor._client")
    def test_max_tokens_raises(self, mock_client):
        mock_client.messages.create.return_value = _mock_response("{}", "max_tokens")
        with pytest.raises(ValueError, match="truncated"):
            extract_invoice_data(b"fake", "image/jpeg")

    @patch("extractor._client")
    def test_invalid_json_raises(self, mock_client):
        mock_client.messages.create.return_value = _mock_response("not json at all")
        with pytest.raises(ValueError, match="invalid"):
            extract_invoice_data(b"fake", "image/jpeg")

    @patch("extractor._client")
    def test_missing_fields_key_raises(self, mock_client):
        mock_client.messages.create.return_value = _mock_response('{"line_items": []}')
        with pytest.raises(ValueError, match="incomplete"):
            extract_invoice_data(b"fake", "image/jpeg")

    @patch("extractor._client")
    def test_missing_line_items_key_raises(self, mock_client):
        mock_client.messages.create.return_value = _mock_response('{"fields": {}}')
        with pytest.raises(ValueError, match="incomplete"):
            extract_invoice_data(b"fake", "image/jpeg")

    @patch("extractor._client")
    def test_non_dict_response_raises(self, mock_client):
        mock_client.messages.create.return_value = _mock_response("[1, 2, 3]")
        with pytest.raises(ValueError, match="invalid"):
            extract_invoice_data(b"fake", "image/jpeg")

    @patch("time.sleep")
    @patch("extractor._client")
    def test_retries_on_connection_error(self, mock_client, mock_sleep):
        payload = json.dumps({"fields": {}, "line_items": []})
        mock_client.messages.create.side_effect = [
            anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")),
            _mock_response(payload),
        ]
        result = extract_invoice_data(b"fake", "image/jpeg")
        assert mock_client.messages.create.call_count == 2
        assert "fields" in result

    @patch("time.sleep")
    @patch("extractor._client")
    def test_raises_after_max_retries(self, mock_client, mock_sleep):
        mock_client.messages.create.side_effect = anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com"),
        )
        with pytest.raises(anthropic.APIConnectionError):
            extract_invoice_data(b"fake", "image/jpeg")
        assert mock_client.messages.create.call_count == 3

    @patch("extractor._client")
    def test_pdf_uses_document_block(self, mock_client):
        payload = json.dumps({"fields": {}, "line_items": []})
        mock_client.messages.create.return_value = _mock_response(payload)
        extract_invoice_data(b"fake", "application/pdf")
        call_args = mock_client.messages.create.call_args
        content = call_args.kwargs["messages"][0]["content"]
        assert content[0]["type"] == "document"

    @patch("extractor._client")
    def test_image_uses_image_block(self, mock_client):
        payload = json.dumps({"fields": {}, "line_items": []})
        mock_client.messages.create.return_value = _mock_response(payload)
        extract_invoice_data(b"fake", "image/png")
        call_args = mock_client.messages.create.call_args
        content = call_args.kwargs["messages"][0]["content"]
        assert content[0]["type"] == "image"
