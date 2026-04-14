FROM python:3.13-slim

# 1. Install system dependencies (netcat for healthchecks)
RUN apt-get update && apt-get install -y netcat-openbsd && rm -rf /var/lib/apt/lists/*

# 2. Setup directory
WORKDIR /app

# 3. Install dependencies (Using your pyproject.toml)
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv export --format requirements-txt > requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn

# 4. Copy source code
COPY . .

# 5. Setup entrypoint
RUN chmod +x entrypoint.sh
ENTRYPOINT ["./entrypoint.sh"]