# Deployment & Installation

This guide covers the standard procedure for deploying the **Codexmetry** using Docker Compose. 

## 1. Prerequisites

Before initializing the installation, ensure your host environment meets the following requirements:

*   **Docker & Docker Compose:** Installed and running.
*   **Network Ports:** 
    *   `5001`: Application Interface.
    *   `5432`: Internal Database Engine (isolated by default).
*   **Architecture:** x86_64 or ARM64 (PostgreSQL 17 compatible).

---

## 2. Step-by-Step Installation

### Step 1: Create the Project Environment
Establish a dedicated directory to serve as the host anchor for your data volumes and configuration files.

```bash
mkdir codexmetry && cd codexmetry
```

### Step 2: Acquire Orchestration Files
Download the mandatory environment template and the Docker Compose manifest directly from the official repository.

```bash
# Download the environment template
curl -L https://raw.githubusercontent.com/jhjang101/codexmetry/main/.env.example -o .env

# Download the compose file
curl -L https://raw.githubusercontent.com/jhjang101/codexmetry/main/compose.yaml -o compose.yaml
```

### Step 3: Configure Environment Variables
Edit the `.env` file to establish your unique system credentials. 

!!! warning "Security Requirement"
    You must change the `INITIAL_ADMIN_PASSWORD` and generate a unique `SECRET_KEY`. To generate a high-entropy key, run the following command in your terminal:
    `python3 -c 'import secrets; print(secrets.token_hex(32))'`

```bash
nano .env
```

### Step 4: Launch the Fortress
Initialize the containers. The engine will automatically detect the empty database and perform the initial schema migration and system record seeding.

```bash
docker compose up -d
```

---

## 3. Post-Deployment Verification

Once the containers are active, you can verify the integrity of the installation:

1.  **UI Access:** Navigate to `http://localhost:5001`.
2.  **Logs:** Check the system initialization log for any database errors:
    ```bash
    docker compose logs -f app
    ```
3.  **Root Login:** Use the credentials defined in your `.env` file to access the Admin dashboard.

---

## 4. Data Persistence & Volumes

Codexmetry is designed for data durability. By default, your data is mapped to specific directories on your host machine to ensure it survives container updates.

| Container Path | Host Path (Local) | Logical Purpose |
| :--- | :--- | :--- |
| `/var/lib/postgresql/data` | `./postgres` | Physical Database storage. **(Protected)** |
| `/app/app/static/uploads` | `./data/uploads` | Documents, Images, and Attachments. |
| `/app/app/backups` | `./data/backups` | SQL Snapshots and System Archives. |
| `/app/app/logs` | `./data/logs` | Audit Trails and System Activity Logs. |

!!! warning "Permissions & Data Access"
    If the application cannot save uploads or generates "Permission Denied" errors in the logs, synchronize the host directory permissions for the **asset subdirectories** only:
    
    ```bash
    sudo chown -R $USER:$USER ./data/uploads ./data/backups ./data/logs
    ```
    
    !!! danger "Engine Protection"
        **Never** run `chown` on the `./postgres` directory. This folder is managed exclusively by the database engine. Changing its ownership will cause the database to crash and refuse to restart.

---

## 5. Basic Operations

| Action             | Command                                               |
| :----------------- | :---------------------------------------------------- |
| **Stop System**    | `docker compose stop`                                 |
| **Restart System** | `docker compose restart`                              |
| **Update Image**   | `docker compose pull && docker compose up -d`         |

---

## 6. Complete System Reset (Destructive)

In scenarios where a total environment wipe is required (e.g., preparing for a fresh production deployment or clearing a test environment), use the following command:

```bash
docker compose down -v
```

!!! danger "Critical Data Warning"
    The -v flag instructs Docker to **permanently delete the internal database volumes**. While your mapped host data (backups/logs) will remain on your physical disk, the live state of the application will be destroyed.

    **Ensure you have a validated Full System Archive (.zip) before performing this action.**