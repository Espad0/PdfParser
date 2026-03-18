"""Invoice field extraction using Claude's multimodal capabilities."""

import base64
import json
import re

import anthropic

from config import ANTHROPIC_API_KEY, MODEL_NAME

EXTRACTION_PROMPT = """\
You are an invoice data extraction specialist. Analyze the provided invoice document \
and extract structured data. The invoice may be in any language — extract values as they \
appear, keeping proper nouns, addresses, and monetary values in their original form.

Extract the following 10 key fields:
1. invoice_number — The invoice, order, or document reference number
2. invoice_date — The invoice date (normalize to YYYY-MM-DD when possible)
3. supplier_name — Name of the supplier / vendor / seller
4. supplier_address — Full address of the supplier
5. client_name — Name of the client / buyer / customer
6. client_address — Full address of the client
7. supplier_tax_id — Supplier's VAT / tax / company registration number
8. client_tax_id — Client's VAT / tax / company registration number
9. total_excl_vat — Total amount excluding VAT/tax (number only)
10. total_incl_vat — Total amount including VAT/tax (number only)

Also extract these supplementary fields:
- currency — ISO currency code or as shown on the document
- vat_rate — The VAT/tax rate as a percentage string (e.g. "20%")
- vat_amount — The VAT/tax amount (number only)

Extract ALL line items. Each line item should have:
- description — Item or service description
- quantity — Number of units (number)
- unit_price — Price per unit (number)
- unit — Unit of measurement (e.g. "pc", "hour", "km", "h")
- total — Total for the line item (number)

Respond with ONLY a valid JSON object in this exact structure — no markdown fences, \
no commentary:
{
  "fields": {
    "invoice_number": "...",
    "invoice_date": "...",
    "supplier_name": "...",
    "supplier_address": "...",
    "client_name": "...",
    "client_address": "...",
    "supplier_tax_id": "...",
    "client_tax_id": "...",
    "total_excl_vat": 0.0,
    "total_incl_vat": 0.0,
    "currency": "...",
    "vat_rate": "...",
    "vat_amount": 0.0
  },
  "line_items": [
    {
      "description": "...",
      "quantity": 0,
      "unit_price": 0.0,
      "unit": "...",
      "total": 0.0
    }
  ]
}

Rules:
- Numeric fields (totals, quantities, prices) must be JSON numbers, not strings.
- If a field is not found in the document, use null.
- Include every distinct line item, even if they belong to different sections.
"""


def extract_invoice_data(file_bytes: bytes, mime_type: str) -> dict:
    """Send document to Claude and extract structured invoice data.

    Args:
        file_bytes: Raw bytes of the document.
        mime_type: MIME type (application/pdf or image/*).

    Returns:
        Parsed dict with 'fields' and 'line_items' keys.

    Raises:
        ValueError: If Claude's response cannot be parsed as JSON.
        anthropic.APIError: On API-level failures.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    if mime_type == "application/pdf":
        doc_block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(file_bytes).decode(),
            },
        }
    else:
        doc_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": base64.standard_b64encode(file_bytes).decode(),
            },
        }

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    doc_block,
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )

    raw_text = response.content[0].text.strip()

    # Strip markdown code fences if present
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse model response as JSON: {exc}\nRaw: {raw_text[:500]}"
        ) from exc

    if "fields" not in data or "line_items" not in data:
        raise ValueError(
            "Model response missing required keys ('fields', 'line_items')."
        )

    return data
