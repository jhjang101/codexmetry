# Restoration & Disaster Recovery

This guide provides the forensic procedures for restoring the Codexmetry environment from a previously generated **Database Snapshot (.sql)** or **Full System Archive (.zip)**.

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

2. The Migration Version Sync (Critical)

!!! danger "Forensic Requirement" 
    Restoring a database often overwrites the alembic_version table with an older ID. If your application database version is newer than the backup, the system will become confused during the next update.

Immediately after injecting the SQL data, you must synchronize the application's migration state:

1.  Enter the App Container:
    docker exec -it codexmetry_app /bin/sh
2.  Stamp the Registry:
    flask db stamp head
    Logic: This tells the system: "The database I just restored is now aligned
    with the latest schema version in the code."

3. Full System Restoration (.zip)

To restore from a Full System Archive (which includes both the database and
physical attachments like product images and invoice PDFs):

1.  Unzip the Archive: Extract the contents on your host machine. You will see a
    .sql file and an uploads/ folder.
2.  Restore Uploads: Copy the extracted uploads/ folder into your mapped host
    directory:
    cp -r ./extracted_path/uploads/* ./data/uploads/
3.  Restore Database: Follow the SQL injection steps in Section 1 using the
    extracted .sql file.
4.  Fix Permissions: Ensure the Docker container can read the newly moved files:
    sudo chown -R $USER:$USER ./data

4. Verification

After restoration, perform the following high-integrity checks:

  - Check Deal Integrity: Open an existing Order and verify the Order Tree
    displays all related documents.
  - Verify Attachments: Open an Invoice and attempt to view a previously
    generated PDF.
  - Audit Check: Verify that the Forensic Timeline shows the historical actions
    contained in the backup.
