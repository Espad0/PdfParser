# High-Level Scalable Architecture

## 1. System Overview

```
                    ┌──────────────┐
    Users ─────────►│  Ingestion   │
  (Telegram/Email)  │   Gateway    │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐     ┌────────────────┐
                    │  Task Queue  │────►│  Worker Pool   │
                    │  (Celery /   │     │  (Extraction   │
                    │   SQS)       │     │   Workers)     │
                    └──────────────┘     └───────┬────────┘
                                                 │
                              ┌──────────────────┼──────────────────┐
                              │                  │                  │
                       ┌──────▼─────┐   ┌───────▼───────┐  ┌──────▼──────┐
                       │  Document  │   │  LLM Service  │  │  Metadata   │
                       │  Storage   │   │  (Claude API) │  │  Database   │
                       │  (S3)      │   │               │  │  (Postgres) │
                       └────────────┘   └───────────────┘  └─────────────┘
```

## 2. Current POC vs. Production: Throughput Gap

The current proof-of-concept bot processes invoices sequentially (~1–3/min, limited by Claude API latency). The architecture below is designed to close this gap:

| POC Limitation | Production Solution | Expected Improvement |
|----------------|--------------------|-----------------------|
| Sequential processing (1 doc at a time) | Horizontally scaled worker pool behind a task queue | Process N docs in parallel (N = worker count) |
| Telegram polling | Webhook-based ingestion | Lower latency, no wasted poll cycles |
| No retry on validation failure | Agentic retry-with-feedback loop (§4) | Higher first-pass accuracy, fewer manual corrections |
| Single Claude model for all invoices | Model routing (Haiku for simple, Sonnet/Opus for complex) | Lower cost and latency for straightforward invoices |
| No caching | Content-hash deduplication | Skip re-extraction for duplicate submissions |
| No monitoring | Metrics, alerting, and data quality dashboards (§6) | Proactive issue detection, prompt improvement signals |

## 3. Data Pipeline

### Ingestion Layer
- **Telegram Bot Service**: Receives documents via Telegram Bot API. Runs as a stateless service behind a webhook (not polling) for production.
- **Email Ingestion**: Dedicated mailbox with an IMAP listener or inbound email service (e.g., SendGrid Inbound Parse, AWS SES). Extracts attachments and metadata.
- **API Gateway** (optional): REST/gRPC endpoint for programmatic submissions from internal systems.

All channels normalize to a common internal message format:
```json
{
  "source": "telegram|email|api",
  "user_id": "...",
  "reply_to": "chat_id|email_address",
  "document": {"storage_key": "s3://...", "mime_type": "...", "size_bytes": 0},
  "received_at": "ISO-8601"
}
```

### Processing Pipeline
1. **Upload & Store**: Raw document is immediately stored in object storage (S3) and assigned a unique job ID.
2. **Enqueue**: A task message is published to the job queue with the job ID and storage reference.
3. **Extract**: A worker picks up the task, downloads the document from S3, sends it to the LLM, and receives structured JSON.
4. **Validate**: Extracted data goes through the validation layer (same logic as the POC).
5. **Persist**: Validated results are written to the metadata database (PostgreSQL with JSONB columns for flexible schema).
6. **Respond**: Worker sends results back via the original channel (Telegram message, email reply, API callback).

### Storage Solution

| Data Type | Storage | Rationale |
|-----------|---------|-----------|
| Raw documents (PDF, images) | S3 / GCS | Cheap, durable, scalable blob storage |
| Extracted structured data | PostgreSQL (JSONB) | Queryable, transactional, supports evolving schemas |
| Generated Excel files | S3 (ephemeral, TTL) | Temporary artifacts, auto-expire after delivery |
| Job status & audit trail | PostgreSQL | Relational queries for reporting and monitoring |

## 4. AI Agentic Workflow

The extraction pipeline follows an **agentic pattern** with built-in self-correction:

```
Document ──► [Pre-check Agent] ──► [Extraction Agent] ──► [Validation Agent] ──► Result
                  │                      │                       │
                  │                      │              ┌────────▼────────┐
                  │                      │              │  Errors found?  │
                  │                      │              │  Re-extract     │
                  │                      │              │  with feedback   │
                  │                      │              └─────────────────┘
```

- **Pre-check Agent**: Classifies document type, detects language, checks quality (blur, rotation). Can reject unprocessable inputs early with a helpful error message.
- **Extraction Agent**: Core LLM call with structured output. Uses the document type classification to select an optimized prompt template.
- **Validation Agent**: Runs cross-checks (totals, VAT, line items). If validation fails, it feeds the specific errors back to the Extraction Agent for a targeted retry (max 1-2 retries) with the validation errors included in the prompt context.

This retry-with-feedback loop significantly improves accuracy without requiring fine-tuning.

## 5. Scalability Considerations

### Handling Increased Volume

| Concern | Approach |
|---------|----------|
| **Concurrent documents** | Horizontally scale stateless workers behind a task queue. Each worker processes one document independently. |
| **LLM throughput** | Use API rate limiting and request batching. Multiple API keys or tier upgrades for higher RPM. |
| **Storage growth** | S3 lifecycle policies to archive/delete old documents. Partition PostgreSQL tables by date. |
| **Multi-tenant isolation** | Tenant-scoped queues or priority lanes. Per-tenant rate limits to prevent noisy-neighbor issues. |
| **Global availability** | Deploy ingestion services in multiple regions. Central processing cluster (or regional if latency-sensitive). |

### Potential Bottlenecks & Solutions

| Bottleneck | Impact | Solution |
|------------|--------|----------|
| **LLM API rate limits** | Processing stalls under load | Queue-based backpressure + exponential backoff. Cache results for duplicate documents (content-hash based dedup). |
| **Large/complex documents** | Slow extraction, higher cost | Pre-process: split multi-page invoices, compress images. Set per-document timeouts. Consider routing simple invoices to cheaper/faster models. |
| **Database writes under high load** | Insertion lag | Batch writes, use write-ahead buffer. Async persistence — respond to user first, persist after. |
| **File download from Telegram/email** | Network I/O bottleneck | Async I/O with connection pooling. Download to S3 first, then process from S3 (decouples ingestion from processing). |
| **Cold starts** | Latency spike for first requests | Keep minimum worker pool warm. Pre-load model connections. |

### Cost Optimization
- **Model routing**: Use a faster/cheaper model (e.g., Haiku) for simple, well-structured invoices; reserve larger models for complex or multi-language documents.
- **Caching**: Hash document content; skip re-extraction for duplicate submissions.
- **Prompt optimization**: Keep prompts concise; avoid unnecessary instructions that increase token usage.

## 6. Monitoring & Observability

- **Metrics**: Extraction latency (p50/p95/p99), success rate, validation pass rate, queue depth, worker utilization.
- **Alerting**: Queue depth exceeding threshold, extraction error rate spike, LLM API error rate.
- **Logging**: Structured logs with job ID correlation. Store raw LLM responses for debugging.
- **Data quality dashboard**: Track which fields are most often null or fail validation — signals for prompt improvement.
