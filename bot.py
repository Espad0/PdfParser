"""Telegram bot for invoice document parsing."""

import logging
import tempfile
import traceback

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import MAX_FILE_SIZE_MB, SUPPORTED_MIME_TYPES, TELEGRAM_BOT_TOKEN
from excel_export import create_excel
from extractor import extract_invoice_data
from validator import validate

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Welcome to Invoice Parser Bot!\n\n"
    "Send me an invoice as a PDF file or photo, and I will extract key fields "
    "and line items from it.\n\n"
    "Supported formats: PDF, JPEG, PNG, WebP\n"
    "Invoices in any language are supported."
)


# ---- Handlers ----


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_TEXT)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_TEXT)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle a file sent as a Telegram document (PDF or image)."""
    doc = update.message.document
    mime = doc.mime_type or ""

    if mime not in SUPPORTED_MIME_TYPES:
        await update.message.reply_text(
            f"Unsupported file type: {mime}\n"
            "Please send a PDF or image (JPEG/PNG/WebP)."
        )
        return

    if doc.file_size and doc.file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        await update.message.reply_text(
            f"File too large (max {MAX_FILE_SIZE_MB} MB). Please send a smaller file."
        )
        return

    await _process_file(update, doc.file_id, mime)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle a photo (compressed image) sent via Telegram."""
    # Telegram sends multiple sizes; pick the largest
    photo = update.message.photo[-1]
    await _process_file(update, photo.file_id, "image/jpeg")


async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please send an invoice document (PDF or photo) to get started.\n"
        "Type /help for more information."
    )


# ---- Core processing ----


async def _process_file(update: Update, file_id: str, mime_type: str):
    """Download file, extract data, validate, and reply with results + Excel."""
    status_msg = await update.message.reply_text("Processing your invoice...")

    try:
        # Download file
        tg_file = await update.get_bot().get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()

        # Extract fields via Claude
        await status_msg.edit_text("Extracting invoice data with AI...")
        data = extract_invoice_data(bytes(file_bytes), mime_type)

        # Validate
        validation = validate(data)

        # Build response text
        response_text = _format_response(data, validation)

        # Generate Excel
        excel_bytes = create_excel(data)

        # Send response
        await status_msg.edit_text(response_text, parse_mode="HTML")

        # Send Excel file
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
            tmp.write(excel_bytes)
            tmp.flush()
            tmp.seek(0)
            await update.message.reply_document(
                document=tmp,
                filename="invoice_data.xlsx",
                caption="Extracted invoice data",
            )

    except Exception as exc:
        logger.error("Processing failed: %s", traceback.format_exc())
        await status_msg.edit_text(
            f"Sorry, processing failed:\n{type(exc).__name__}: {exc}"
        )


def _format_response(data: dict, validation) -> str:
    """Format the extracted data as a readable Telegram message (HTML)."""
    fields = data.get("fields", {})
    items = data.get("line_items", [])

    currency = fields.get("currency", "")

    lines = ["<b>Invoice #{}</b>  |  {}".format(
        fields.get("invoice_number", "N/A"),
        fields.get("invoice_date", "N/A"),
    )]

    # Parties
    lines.append("")
    lines.append(
        f"<b>Supplier:</b> {fields.get('supplier_name', 'N/A')}"
        f"\n{fields.get('supplier_address', '')}"
        f"\nTax ID: {fields.get('supplier_tax_id', 'N/A')}"
    )
    lines.append("")
    lines.append(
        f"<b>Client:</b> {fields.get('client_name', 'N/A')}"
        f"\n{fields.get('client_address', '')}"
        f"\nTax ID: {fields.get('client_tax_id', 'N/A')}"
    )

    # Totals
    vat_rate = fields.get("vat_rate", "N/A")
    vat_amount = fields.get("vat_amount")
    lines.append("")
    lines.append(
        f"<b>Totals ({currency}):</b>"
        f"\nExcl. VAT: {_fmt_num(fields.get('total_excl_vat'))}"
        f"\nVAT {vat_rate}: {_fmt_num(vat_amount)}"
        f"\n<b>Incl. VAT: {_fmt_num(fields.get('total_incl_vat'))}</b>"
    )

    # Line items
    lines.append("")
    lines.append(f"<b>Line Items ({len(items)}):</b>")
    for i, item in enumerate(items, 1):
        desc = item.get("description", "N/A")
        qty = item.get("quantity", "?")
        total = _fmt_num(item.get("total"))
        lines.append(f"{i}. {desc} — {qty} x {_fmt_num(item.get('unit_price', 0))} = {total}")

    # Validation
    if not validation.is_valid or validation.warnings:
        lines.append("")
        if validation.errors:
            lines.append("<b>Errors:</b>")
            for e in validation.errors:
                lines.append(f"- {e}")
        if validation.warnings:
            lines.append("<b>Warnings:</b>")
            for w in validation.warnings:
                lines.append(f"- {w}")

    return "\n".join(lines)


def _fmt_num(value) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


# ---- Application factory ----


def create_bot() -> Application:
    """Build and configure the Telegram bot application."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other)
    )

    return app
