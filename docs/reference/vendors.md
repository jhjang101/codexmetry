# Vendors Technical Reference

The Vendors module serves as the primary master data anchor for operational costs and supply chain documents. Every Expense must be associated with a valid Vendor record to ensure accurate cost tracking and vendor liability reporting.

---

## 1. Account Identity

*   **Vendor Label** [Input]: The primary identifier for internal use to label the vendor (e.g., "Amazon Business").
    *   *Integrity Constraint*: This field is **Unique**. The system prevents the creation of duplicate account labels to ensure expenses and outgoing orders are never assosiated with the wrong legal entity.
*   **Website URL** [Input]: The official website or portal link for the vendor.
*   **Company Address** [Input]: The physical or remittance address for the vendor. 
    *   *Logic*: This field is used *"As-is"* to populate the **Vendor** address block on issued Expense PDFs (Vendor Purchase Orders).

---

## 2. Personnel & Contacts

Codexmetry supports multiple contacts per vendor account to manage relationships across sales, support, and billing departments.

*   **First & Last Name** [Input]: The identity of the individual contact.
*   **Email Address** [Input]: The primary communication channel for the contact.
*   **Phone Number** [Input]: The direct line for the contact.
*   **Primary Contact** [Property]: A system-derived logic that identifies the topmost contact record in the list.
    *   *Ripple*: The Primary Contact’s name and email serve as the default display and search identifiers in the main **Vendor List**.

---

## 3. Metadata & Auditing

*   **Active Status (is_active)** [System]: A boolean flag used for soft-deletion.
    *   *Integrity Note*: Archiving a vendor removes them from dropdown selectors but preserves their identity in historical financial reports and existing Expense records to prevent data orphaning.
*   **Created By / At** [System]: Captures the identity of the user who initialized the account and the UTC timestamp of creation.
*   **Updated By / At** [System]: Tracks the most recent user to modify the account details and the timestamp of that change.
*   **Activity Log** [System]: Displays the chronological record of every change made to the account, including user identity and the modified fields.