# syntax=docker/dockerfile:1
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source (src package).
COPY src ./src

EXPOSE 8080

# Streamable HTTP MCP server + test UIs (FastAPI + official MCP Python SDK).
CMD ["python", "-m", "src.main"]
