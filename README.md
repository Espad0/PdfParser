# Invoice Parser Bot

AI-powered Telegram bot that extracts structured data from invoice documents in any language.

## Features

- Accepts invoices as **PDF files** or **photos** (JPEG, PNG, WebP) via Telegram
- Uses **Claude** (multimodal LLM) to extract text and structured fields from documents
- Extracts **10 key fields** + all **line items**
- **Validates** extracted data (cross-checks totals, VAT, line item sums)
- Returns results as a **structured message** + **Excel file** attachment

## Extracted Fields

| # | Field | Description |
|---|-------|-------------|
| 1 | Invoice Number | Document reference / order number |
| 2 | Invoice Date | Normalized to YYYY-MM-DD |
| 3 | Supplier Name | Vendor / seller name |
| 4 | Supplier Address | Full address |
| 5 | Client Name | Buyer / customer name |
| 6 | Client Address | Full address |
| 7 | Supplier Tax ID | VAT / company registration number |
| 8 | Client Tax ID | VAT / company registration number |
| 9 | Total (excl. VAT) | Pre-tax total |
| 10 | Total (incl. VAT) | Final total with tax |

Additional: currency, VAT rate, VAT amount, and all line items with description, quantity, unit price, unit, and total.

## Setup

### Prerequisites

- Python 3.11+
- A Telegram Bot token (create via [@BotFather](https://t.me/BotFather))
- An Anthropic API key ([console.anthropic.com](https://console.anthropic.com))

### Installation

```bash
cd HomeWork
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Get a Telegram Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts — choose a name and a username for your bot.
3. BotFather will reply with a token like `7650525997:AAH...`. Copy it.

### Get an Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com) and sign in (or create an account).
2. Navigate to **API Keys** in the left sidebar.
3. Click **Create Key**, give it a name, and copy the key (it starts with `sk-ant-...`).
4. Make sure you have credits or a payment method on your account — API calls are billed per usage.

### Configuration

Create a `.env` file in the project root and paste both values:

```bash
cp .env.example .env
```

Then edit `.env`:

```
TELEGRAM_BOT_TOKEN=7650525997:AAH...
ANTHROPIC_API_KEY=sk-ant-...
```

The bot will refuse to start if either variable is missing or still set to a placeholder.

### Run

```bash
python main.py
```

## Usage

1. Open your bot in Telegram
2. Send `/start` to see instructions
3. Send an invoice (PDF file or photo)
4. Receive structured extraction results + Excel file

## Project Structure

```
├── main.py          # Entry point
├── bot.py           # Telegram bot handlers and response formatting
├── extractor.py     # Claude API integration for document parsing
├── validator.py     # Data validation and cross-checks
├── excel_export.py  # Excel workbook generation
├── config.py        # Configuration and environment variables
├── requirements.txt
├── .env.example
├── architecture.md  # High-level scalable architecture (optional)
└── sample_invoice.pdf
```

## Security

The bot processes untrusted user-uploaded documents via an LLM, which creates a prompt injection attack surface. The following defenses are in place:

### Prompt Injection Mitigation

- **System/user prompt separation**: Extraction instructions are passed via Claude's `system` parameter, which the model treats with higher authority than user-message content. This makes it significantly harder for text embedded in a malicious PDF or image to override the bot's behavior.
- **Explicit anti-injection instructions**: The system prompt tells the model to never follow instructions found inside the document and to ignore any override attempts.
- **Strict output schema enforcement**: LLM output is run through `_sanitize_output()` which only keeps whitelisted keys, coerces numeric fields to `float`, truncates strings to 500 characters, and caps line items at 500. Any unexpected keys injected by a manipulated response are silently stripped.

### Output Escaping

- **HTML escaping**: Every LLM-extracted value is passed through `html.escape()` before being embedded in the Telegram HTML message, preventing HTML/script injection via crafted invoice data.
- **Validation messages escaped**: Error and warning strings from the validator are also HTML-escaped before display.

### Information Disclosure Prevention

- **Generic user-facing errors**: Exception details (stack traces, raw LLM output) are logged server-side only. Users see a generic "processing failed" message.
- **No input reflection**: User-controlled values (e.g., MIME type) are not echoed back in error messages.

### Credential Handling

- API keys and tokens are loaded from a `.env` file which is excluded from version control via `.gitignore`.
- The bot refuses to start if credentials are missing or set to placeholder values.

### Input Validation

- Only whitelisted MIME types (PDF, JPEG, PNG, WebP, GIF) are accepted.
- File size is capped at 20 MB before any processing occurs.

## Throughput & Limits

### Current Processing Model

The bot processes invoices **sequentially** — one document at a time per bot instance. Each invoice goes through: file download → Claude API extraction → validation → Excel generation → response.

### Processing Limits

| Limit | Value | Source |
|-------|-------|--------|
| Max file size | 20 MB | `config.py` |
| Max LLM output tokens | 4,096 | `extractor.py` |
| Max line items per invoice | 500 | `extractor.py` |
| Max string field length | 500 chars | `extractor.py` |
| Max additional fields | 20 | `extractor.py` |
| VAT cross-check tolerance | ±2% | `validator.py` |

### Estimated Throughput

| Metric | Estimate | Notes |
|--------|----------|-------|
| **Invoices per minute** | ~1–3 | Bottlenecked by Claude API latency (5–30s per call) |
| **Concurrent users** | Sequential | Requests are queued; no parallel processing |

### Bottlenecks

1. **Claude API latency** — the dominant factor. Each invoice requires one multimodal API call; response time varies with document complexity.
2. **Sequential processing** — handlers are async but each document is fully processed before the next one starts. No worker pool or task queue.
3. **External rate limits** — Anthropic API rate limits (RPM/TPM, tier-dependent) and Telegram Bot API limits (~30 msgs/sec across chats) cap sustained throughput.

For the scalable production architecture that addresses these limits, see [architecture.md](architecture.md).

## Design Decisions

- **Claude (LMM)**: Chosen for native multimodal support — processes PDFs and images directly without a separate OCR step. Handles multilingual documents natively.
- **Structured JSON extraction**: Single-pass prompt returns validated JSON, avoiding fragile regex or template-matching approaches.
- **Validation layer**: Cross-checks totals and line items to catch extraction errors before returning results.
- **Excel output**: Uses openpyxl for clean, styled spreadsheets that are immediately usable.
