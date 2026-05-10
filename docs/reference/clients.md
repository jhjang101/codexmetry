# Clients Technical Reference

The Clients module serves as the primary master data anchor for the Sales and Fulfillment documents. Every Quote, Purchase Order, and Invoice must be associated with a valid Client record to ensure data integrety and accurate reporting.

---

## 1. Account Identity

- **Client Label** [Input]: The primary identifier for internal use to label the client (e.g., "General Electric-Shipping").
  - *Display Logic:* In system dropdowns, this field appears as the **Label (Primary Contact Name)** to provide users with immediate account identification.
  - *Integrity Constraint:* This field is **Unique**. The system prevents the creation of duplicate account labels to ensure payments and orders are never assosiated with the wrong legal entity.
- **Company Address** [Input]: The shipping or billing address for the account.
  - *Logic:* This field is used *"As-is"* to populate the **Ship To** and **Bill To** Address fields on all issued Invoices and the **TO** section on all issued Quotes.

---

## 2. Personnel & Contacts

Codexmetry supports multiple contacts per client account to accommodate complex procurement or departmental structures.

- **First & Last Name** [Input]: The identity of the individual contact.
- **Email Address** [Input]: The primary communication channel for the contact.
- **Phone Number** [Input]: The direct line for the contact.
- **Primary Contact** [Property]: A system-derived logic that identifies the topmost contact in the list.
  - *Ripple:* The Primary Contact’s name and email are used as the default display and search identifiers in the main **Client List** and the parenthetical info in document dropdowns.

---

## 3. Metadata & Auditing

- **Active Status (is_active)** [System]: A boolean flag used for soft-deletion.
  - *Integrity Note:* Archiving a client removes them from all dropdown selectors but preserves their identity in all historical financial reports and existing documents.
- **Created By / At** [System]: Captures the identity of the user who initialized the account and the UTC timestamp of creation.
- **Updated By / At** [System]: Tracks the most recent user to modify the account details and the timestamp of that change.
- **Activity Log** [System]: Displays the chronological record of every change made to the account, including user identity and the modified fields.
