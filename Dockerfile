# --- STAGE 1: The Builder ---
FROM python:3.13-slim-bookworm AS builder

# 1. Install uv binary directly (Official Astral method)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 2. Set working directory
WORKDIR /app

# 3. Install dependencies into a localized path
# --no-install-project ensures we only build the environment layer first
COPY pyproject.toml uv.lock ./
RUN /bin/uv sync --frozen --no-install-project --no-dev


# --- STAGE 2: The Final Image ---
FROM python:3.13-slim-bookworm

# 4. Install necessary system runtime tool
RUN apt-get update && apt-get install -y --no-install-recommends \
    netcat-openbsd \
    curl \
    ca-certificates \
    gnupg \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libglib2.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# 5. Add official PostgreSQL Repo and install Client v17
RUN install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 6. Copy the pre-built Python environment from the builder
COPY --from=builder /app/.venv /app/.venv

# 7. Copy the source code
COPY . .

# 8. Security & Execution
# Update PATH so the app uses the virtualenv's Python/Flask automatically
ENV PATH="/app/.venv/bin:$PATH"
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]