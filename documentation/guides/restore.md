# Restoration & Disaster Recovery

This guide provides the procedures for restoring the Codexmetry environment from a previously generated **Database Snapshot (.sql)** or **Full System Archive (.zip)**.

## 1. Restoring the Database (SQL)

If you have a standard `.sql` snapshot located in your `backups/` directory, use one of the following  methods to inject the data into the PostgreSQL engine.

### Method A: Using `docker exec` (Recommended)
This is the cleanest method as it uses the tools already inside the database container.

```bash
# 1. Identify your backup file (e.g., codexmetry_db_20260427_153000.sql)
# 2. Run the injection command
docker exec -i codexmetry_db psql -U admin -d codexmetry < ./data/backups/your_backup_file.sql
```

### Method B: Using Local psql

Use this method if you have the PostgreSQL client installed on your host machine.

```bash
psql -h localhost -p 5432 -U admin -d codexmetry < ./data/backups/your_backup_file.sql
```

## 2. Synchronize & Auto-Upgrade

!!! info "Automatic Schema Alignment"
    After a restoration, your database version might be behind your current application code. Codexmetry features a self-healing entrypoint that automatically aligns the restored data with the latest system requirements.

To trigger the synchronization and apply any missing database migrations:

1.  **Restart the System:**
    ```bash
    docker compose restart
    ```

2.  **Verify the Sync:**
    Monitor the logs to ensure the migration completed successfully:
    ```bash
    docker compose logs -f app
    ```
    *You should see "Applying database migrations..." followed by "PostgreSQL started".*

---

## 3. Full System Restoration (.zip)

To restore from a **Full System Archive** (which includes both the database and physical attachments like product images and invoice PDFs):

1.  **Unzip the Archive:**
    Extract the contents on your host machine. You will see a `.sql` file and an `uploads/` folder.

2.  **Restore Uploads:**
    Copy the extracted `uploads/` folder into your mapped host directory:
    ```bash
    cp -r ./extracted_path/uploads/* ./data/uploads/
    ```

3.  **Restore Database:**
    Follow the SQL injection steps in **Section 1** using the extracted `.sql` file.

4.  **Finalize & Sync:**
    Perform the system restart to align the data:
    ```bash
    docker compose restart
    ```

5.  **Fix Asset Permissions:**
    If you encounter "Permission Denied" errors when viewing attachments, reset the ownership of the asset directories:
    ```bash
    sudo chown -R $USER:$USER ./data/uploads ./data/backups ./data/logs
    ```

---

## 4. Post-Restoration Checklist

Perform these checks to ensure the "Fortress" is stable:

*   **Order Hub:** Open an existing deal and verify the **Order Tree** accurately displays the document chain.
*   **Asset Linkage:** Open an older Invoice and verify that the generated PDF snapshot opens correctly.
*   **Version Verification:** Run `docker exec -it codexmetry_app flask db current` to confirm the database is at the latest migration ID.