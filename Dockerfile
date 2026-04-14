# --- STAGE 1: The Builder ---
FROM python:3.13-slim AS builder

# 1. Install uv binary directly (Official Astral method)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 2. Set working directory
WORKDIR /app

# 3. Install dependencies into a localized path
# --no-install-project ensures we only build the environment layer first
COPY pyproject.toml uv.lock ./
RUN /bin/uv sync --frozen --no-install-project --no-dev


# --- STAGE 2: The Final Fortress ---
FROM python:3.13-slim

# 4. Install only the absolutely necessary system runtime tool
RUN apt-get update && \
    apt-get install -y --no-install-recommends netcat-openbsd && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 5. Copy the pre-built Python environment from the builder
# This skips the entire installation/cache bloat
COPY --from=builder /app/.venv /app/.venv

# 6. Copy the source code
COPY . .

# 7. Security & Execution
# Update PATH so the app uses the virtualenv's Python/Flask automatically
ENV PATH="/app/.venv/bin:$PATH"
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]