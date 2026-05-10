# Documentation Overview

Welcome to the official technical documentation for **Codexmetry**.

Codexmetry is a high-integrity order management engine designed for startups and small businesses that require absolute data accuracy and unbroken lifecycle accountability. This documentation provides a deep-dive into the system's architecture, logical workflows, and technical field references.

---

## The Philosophy

The system is built upon two distinct logical pillars that ensure your business records remain a "Single Source of Truth."

### CODEX (The Narrative)

An unbroken record of the document lifecycle. Every transaction orbits a unique [Order Registry ID (CDX)](./reference/orders.md). By centralizing the order history, Codexmetry allows you to visualize the entire path of a sale from the initial proposal to the final bank confirmation within a single, connected timeline.

### METRY (The Math)

A precision representation of account health through comprehensive analytics and financial statements. The system provides [business intelligence](./reference/reports.md) by isolating economic performance (**Accrual**) from cash liquidity (**Cash**), supported by 60-month linear trends and interactive performance rankings for clients and products.

---

## Navigation Guide

To get started with the Codexmetry, please refer to the following sections:

### 1. Operational Guides

Step-by-step instructions for deploying and maintaining the system.

- **[Deployment & Installation](./guides/deployment.md)**: Launching the environment using Docker Compose.
- **[Initial Setup](./guides/setup.md)**: Configuring your company identity and lookups.
- **[Document Lifecycle](./guides/workflow.md)**: Standard order management workflows.

### 2. Technical Reference

A comprehensive, field-by-field manual of every module in the application.

- **[Order Registry (CDX)](./reference/orders.md)**: Understanding the deal anchor.
- **[Invoices & Fulfillment](./reference/invoices.md)**: Managing revenue and credit pools.
- **[Settlement & Payments](./reference/payments.md)**: Recording cash and automated reconciliation.

### 3. Disaster Recovery

- **[Restoration Guide](./guides/restore.md)**: Procedures for recovering data from SQL or ZIP archives.
