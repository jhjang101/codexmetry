# Quotes Technical Reference

The Quotes module manages formal proposals issued to clients. It serves as the starting point for most business transactions, allowing for itemized pricing and legal terms to be established before a formal order is initialized.

---

## 1. Identification & Linking

- **Client** [Input]: The primary account holder for the Quote.
- **Quote Number** [Input/System]: The unique identifier for the Quotes.
  - *Logic:* Defaults to the `Q-YYQSSSV` format (Year, Quarter, Sequence, Checksum). Supports manual override for custom numbering schemes.
- **Order Reference (CDX)** [System]: The unique identifier of the linked order.
  - *Logic:* This field remains **blank** while the quote is still a lead. It is only populated after the quote is accepted and linked to a Purchase Order (PO).

---

## 2. Scheduling & Logic

- **Quote Date** [Input]: The date the Quotes is created. Defaults to the current business day.
- **Expiration Date** [Input]: The date until which the offer remains valid.
  - *Logic:* Automatically calculated using the **Quote Expiry (Days)** setting from global configuration, but can be manually adjusted.
- **Status** [Input/System]: The current stage of the Quotes:
  - `Draft`: Work-in-progress; not yet issued to the client.
  - `Sent`: The document has been issued and a PDF has been generated.
  - `Accepted`: The client has accepted the Quotes and it has been converted into a PO.
  - `Expired`: The Quotes has passed its expiration date without conversion.

---

## 3. Financial Data

- **Total Amount** [System]: The sum of all line items (recorded in cents).
- **Integrity Lock** [System]: *(TODO)*
  - *Logic:* Once a Quote is linked to an active order, it becomes **permanently locked** from further editing. This ensures the original Quote remains consistent with the final contract. To modify a locked quote, the link must be removed from the Purchase Order side.

---

## 4. Line Item Details (Sub-form)

- **Product** [Input]: The Product selected from the product catalog.
  - *Logic:* Selection pulls the default unit price and determines the **Document Placement** (Standard, Tax, or Shipping).
- **Description** [Input]: Specific details for the line item, inherited by the PO during conversion.
- **Quantity** [Input]: The number of units being quoted.
- **Unit Price** [Input]: The price per unit (in cents), prefilled from the catalog but overridable for the specific Quote.

---

## 5. Metadata & Auditing

- **Internal Note** [Input]: Private comments for internal use. Not visible on the printed PDF.
- **Terms & Notes** [Input]: Instructions or terms included in the PDF footer. Defaults to global system terms on creation but is editable.
- **Attachments** [Input/System]: Manual files added by the user (e.g., client requests or specifications), and system generated PDFs during the "Issue" process.
- **Version Counter** [System]: Tracks how many times the document has been "Issued." Used to track the version of issued PDFs in the attachment zone.
- **Activity Log** [System]: Displays the chronological record of every change made to the quote, including user identity and the modified fields.
