# Codexmetry

### The Financial Fortress of Order Management

[![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)](https://github.com/jhjang101/codexmetry)
[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](https://opensource.org/licenses/MIT)
[![Docker Ready](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)

**Codexmetry** is a precision-engineered order management engine built for startups and small businesses that require absolute data integrity and lifecycle accountability.

It is designed as a "Financial Fortress," ensuring that every sales follows an unbroken chain of documents from the first proposal to the final settlement.

---

## The Two Pillars

The name **Codexmetry** represents the dual-grip architecture of the system:

- **CODEX (The Narrative):** An unbroken record of the document lifecycle. Every document orbits a unique **Order Registry ID (CDX)**, visualized through a dynamic **Order History** and documented via nested, parent-child audit logs.
- **METRY (The Math):** A precision representation of account health. Built on a strict **integer-math backbone**, providing dual-perspective financial reporting (Accrual vs. Cash) with zero rounding errors.

---

## Core Features

- **Registry-Centric Architecture:** All documents are tied to an immutable CDX anchor, ensuring a perfectly linked data structure.
- **Audit Trails:** Nested logs capture the "Who, When, and Why" of every field-level change.
- **Smart-Sync Automation:** Invoices and POs automatically update statuses based on payment fulfillment and threshold gaps.
- **Deep Business Intelligence:** Comprehensive reporting suite featuring 60-month linear trends, dual-perspective statements (Accrual/Cash), and granular client/product performance analytics.

---

## Quick Start (Docker)

Deploy in minutes using Docker Compose.

### 1. Acquire Orchestration Files

```bash
mkdir codexmetry && cd codexmetry
curl -L https://raw.githubusercontent.com/jhjang101/codexmetry/main/.env.example -o .env
curl -L https://raw.githubusercontent.com/jhjang101/codexmetry/main/compose.yaml -o compose.yaml
```

### 2. Configure Environment

Edit `.env` to set a unique `SECRET_KEY` and your `INITIAL_ADMIN_PASSWORD`.

```bash
sudo nano .env
```

### 3. Launch

```bash
docker compose up -d
```

Access the dashboard at `http://localhost:5001`.

---

## Documentation & Support

For a deep-dive into logical workflows, technical field references, and restoration procedures, visit our official documentation:

**[View Full Documentation](https://jhjang101.github.io/codexmetry/)**

---

## License

Codexmetry is open-source software licensed under the [MIT License](LICENSE).
