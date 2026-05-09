# Payments Technical Reference

The Payments module records incoming cash and reconciles outstanding balances. It acts as the "Settlement" layer, transitioning documents from active debt into completed historical records.

---

## 1. Identification & Linking

- **Payment Number** [Input/System]: The unique identifier for the transaction.
    - *Logic:* Defaults to the `P-YYQSSSV` format (Year, Quarter, Sequence, Checksum). Supports manual override for matching external banking reference numbers.
- **Purchase Order (PO) Number** [Input]: The primary contract being paid.
    - *Requirement:* A PO link is mandatory for every payment to preserve order integrity.
- **Order Registry (CDX)** [System]: Inherited from the source Purchase Order. Ensures the payment is attributed to the correct PO for profitability reporting.
- **Invoice Number** [Input]: (Optional) The specific invoice being paid.
    - *Prepayment Logic:* If this field is left **blank**, the payment is treated as a **Deposit**. These funds enter the order's "Credit Pool" and can later be applied to future invoices through "Applied Deposit" line items.

---

## 2. The Payer Architecture

Codexmetry distinguishes between the account owner and the actual source of funds:

- **Client** [Input]: The primary business account responsible for the order.
- **Paid From (Payer)** [Input]: The actual entity issuing the payment (e.g., a procurement company or a specific department paying on behalf of the client). 
    - *Default:* Prefills with the Client or the Invoice's "Bill To" selection but remains manually overridable for the specific Payment.

---

## 3. Financial Data

- **Amount** [Input]: The total value received (recorded in cents).
    - *Flexibility:* Supports positive values for standard receipts and negative values for formal refunds or reversals.
- **Payment Date** [Input]: The date the funds were confirmed in the bank. Defaults to the current business day.
- **Payment Type** [Input]: The method of transfer (e.g., Wire Transfer, Credit Card, Check). This field is required for accurate cash-flow categorization.

---

## 4. Integrity Guards & Ripples

The Payments module implements several ntegrity protections to preserve financial accuracy:

- **Amount Reduction Guard**:
    - *Logic:* For Prepayments (Deposits), the system blocks any attempt to reduce the payment amount if those funds have already been consumed through an "Applied Deposit" on an active invoice.
- **Archive Protection**:
    - *Logic:* A payment cannot be archived if its removal would cause a deal's credit pool to become negative. Any invoices consuming that credit must be archived first.
- **Status Sync Trigger**:
    - *Ripple:* Saving or archiving a payment triggers the **Sync Engine**. The system automatically evaluates the linked Invoice balance and the PO fulfillment state, updating statuses to `Completed` or `Open` as needed.
- **Write-off Automation**:
    - *Ripple:* If a payment reduces an invoice balance within the global **Invoice Threshold**, the system automatically generates a "Write-off" Adjustment to settle the remaining gap.

---

## 5. Metadata & Auditing

- **Internal Note** [Input]: Private comments for internal use.
- **Attachments** [Input]: Standard file upload. Commonly used for storing scanned copies of checks or wire confirmations.
- **Activity Log** [System]: Displays the timestamp and user identity for the creation and most recent modification of the record.