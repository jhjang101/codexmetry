# System Maintenance & Stability

The Maintenance module is the "Engine Room" of Codexmetry. Access is strictly restricted to Administrators and provides the tools necessary to ensure data integrity, optimize performance, and manage disaster recovery assets.

---

## 1. System Access Control (Maintenance Mode)

Maintenance Mode acts as a global "Master Lock" for the database.

- **Logic:** When active, all non-admin users are restricted to **Read-Only** access. All `POST`, `PUT`, and `DELETE` requests are blocked at the application gateway.
- **Administrative Privilege:** Administrators remain exempt from this lock, allowing them to perform optimizations or data corrections while the system is quiet.
- **Usage:** Activate this mode before performing large data imports, manual database surgery, or full system archives.

---

## 2. Database Optimization (Vacuum Engine)

Codexmetry uses PostgreSQL 17, which tracks data changes in "pages." Over time, deleted records leave gaps (bloat) that can slow down queries.

- **The Action:** Running **Database Optimization** executes a `VACUUM ANALYZE` command.
- **Reclaim Space:** `VACUUM` marks the space from deleted rows as reusable by the engine.
- **Update Statistics:** `ANALYZE` updates the query planner's internal statistics, ensuring the "Brain" chooses the fastest path to find your data.
- **Recommendation:** Perform this once per week or after archiving a large volume of historical documents.

---

## 3. Snapshot Management

Codexmetry provides a tiered approach to data protection.

### Tier 1: Database Snapshot (.sql)

A lightweight text-based dump of your structured data.

- **Content:** Tables, Rows, Sequences, and Audit Logs.
- **Frequency:** Daily.
- **Impact:** Near-zero. Can be run while users are active.

### Tier 2: Full System Archive (.zip)

A complete "Point-in-Time" image of the entire Fortress.

- **Content:** The Database Snapshot + the entire `uploads/` folder (Product images, Invoice PDFs, etc.).
- **Frequency:** Weekly or before a server migration.
- **Impact (Warning):** Zipping large attachment folders is a resource-heavy operation. On systems with thousands of documents, this will cause a temporary spike in **CPU usage** and **Disk I/O**. It is best performed during off-hours.

---

## 4. Manual "Plan B" Operations (Host Level)

If the application UI is unreachable, you can perform maintenance directly from the host machine terminal.

### Manual Database Dump

```bash
docker exec -t codexmetry_db pg_dump -U admin -d codexmetry > ./manual_backup.sql
```

### Manual Asset Compression

```bash
# Create a zip of all business assets from the project root
zip -r full_assets_backup.zip ./data/uploads ./data/backups ./data/logs
```

---

## 5. Log Oversight

Physical logs are stored in `./data/logs/` and follow a **Self-Cleaning** rotation policy:

- **`audit.log`**: User event stream. 5MB per file, keeping the last 10 versions.
- **`system.log`**: System diagnostics and errors. 5MB per file, keeping the last 10 versions.

!!! warning "Unlink Notification"
    If you manually delete a log file or backup from the host directory while the system is running, the application will continue writing to a "Ghost Handle." You must run `docker compose restart` to force the system to recreate and re-open the physical files.

---

## 6. Recommended Maintenance Schedule

| Interval | Action | Purpose |
| :--- | :--- | :--- |
| **Daily** | DB Snapshot | Basic data protection. |
| **Weekly** | Full System Archive | Sync physical documents with data records. |
| **Weekly** | Database Optimization | Maintain high-speed query performance. |
| **Monthly** | Log Review | Audit system log for unexpected tracebacks or errors. |
| **Quarterly** | Disaster Recovery Test | Restore a backup to a test environment to verify integrity. |
