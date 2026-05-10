# Invoices Technical Reference

The Invoices module manages the official payment requests and records the fulfillment of goods or services. It is the primary driver of the system's [**Accrual Revenue**](./reports.md#a-accrual-basis-performance-statement) metrics and acts as the gatekeeper for the [**Credit Pool**](./payments.md#1-identification-linking).

---

## 1. Identification & Relationship Fields

- **Client** [Input]: The primary account holder for the deal. Selection filters the available Purchase Orders and defaults the "Ship To" address on the PDF.
- **Purchase Order (PO) Number** [Input]: The source document for the invoice.
  - *Ripple:* Selecting a PO automatically prefills the **Bill To**, **Customer PO #**, **Terms**, and all remaining unbilled **Line Items**.
- **Order Registry (CDX)** [System]: Inherited automatically from the linked Purchase Order. This immutable link ensures the invoice is correctly grouped in the Order History and financial reports.
- **Invoice Number** [Input/System]: The unique [identifier](./settings.md#the-identifier-structure) for the document.
  - *Logic:* Defaults to the `I-YYQSSSV` format (Year, Quarter, Sequence, Checksum) but allows manual override for custom numbering schemes.
- **Bill To** [Input]: The specific department or entity within the client's organization responsible for payment. Defaults to the PO's Bill To selection.
- **Customer PO #** [Input]: A secondary reference field, typically used to store the client's internal tracking number. Inherited from the PO.

---

## 2. Scheduling & Logistics

- **Invoice Date** [Input]: The date the fulfillment is recorded. Defaults to the current business day.
  - *Ripple:* This date determines which **Monthly Statement** the revenue is attributed to.
- **Terms (Net Days)** [Input]: The number of days until payment is due.
  - *Logic:* Defaults to the PO override or the [global system default](./settings.md#c-transactional-defaults) (e.g., 30 days). Used to calculate the **Due Date** on the printed PDF.
- **Shipping Carrier** [Input]: The service provider used for delivery.
  - *Ripple:* Selecting a carrier enables the **Ship Date** and **Tracking Number** fields.
- **Ship Date** [Input]: The date the goods left the facility. Defaults to the current date upon carrier selection.
- **Tracking Number** [Input]: The carrier-provided reference for the shipment.

---

## 3. Financial Logic & Status

- **Status** [System/Input]: The current lifecycle stage of the document.
  - `Draft`: Work-in-progress. Items do not yet count toward PO fulfillment or Revenue reports.
  - `Open`: Issued to the client. Revenue is now recognized in Accrual reports.
  - `Completed`: Payment received. The balance is settled.
- **Grand Total** [System]: The raw mathematical sum of all line items (in cents).
  - *Logic:* This value can be **negative** if the "[Applied Deposit](./products.md#4-system-products-internal-logic)" line item exceeds the value of billed products.
- **Total Due** [Property]: The actual billable amount requested from the client.
  - *Math:* Calculated as `max(0, Total Amount)`. It is never negative.
- **Remaining Credit** [Property]: If the total of items is negative (meaning more deposit was applied than goods billed), the excess is represented here.
- **Balance** [Property]: The amount remaining to be paid.
  - *Math:* `Total Due` minus `Sum of Active Payments`.
  - *Ripple:* If this value falls below the [**Invoice Threshold**](./settings.md#a-financial-automation), the system automatically triggers the "Completed" status and generates a [**Write-off Adjustment**](./adjustments.md#4-system-protection-automation).

---

## 4. Line Item Details (Sub-form)

- **Product** [Input]: The Product from product catalog.
  - *Logic:* Selection pulls the default unit price and determines [**Document Placement**](./products.md#2-classification-logic) (Standard, Tax, or Shipping).
- **Description** [Input]: Specific details for this line. Prefilled from the source PO line.
- **Quantity** [Input]: The number of units being fulfilled.
  - *Logic:* When generating from a PO, this defaults to the "Remaining Qty."
- **Unit Price** [Input]: The price per unit in cents.
- **PO Line Link (po_item_id)** [System]: A hidden database link to the specific row on the original Purchase Order.
  - *Logic:* This link is **critical** for preventing "Double-Billing." It ensures the system knows exactly which units of a contract have been fulfilled.

---

## 5. Metadata & Auditing

- **Internal Note** [Input]: Private comments for internal use. Not visible on the printed PDF.
- **Terms & Notes** [Input]: Instructions or terms included in the PDF footer. Defaults to [global system terms](./settings.md#c-transactional-defaults) on creation but is editable.
- **Version Counter** [System]: Increments every time the document is "Issued." Used to track the version of issued PDFs in the attachment zone.
- **Attachments** [Input/System]: Manual files added by the user (e.g., proof of delivery), and system generated PDFs during the "Issue" process.
- **Activity Log** [System]: Displays the chronological record of every change made to the invoice, including user identity and the modified fields.
