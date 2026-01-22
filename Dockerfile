# Use official Python image
FROM python:3.11-slim-trixie

# Set work directory
WORKDIR /app


# Install system dependencies (add curl, unzip)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl unzip \
    && rm -rf /var/lib/apt/lists/*


# Add uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Download xray core binary
RUN mkdir -p /app/xray-bin \
    && curl -L -o /app/xray-bin/xray.zip "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip" \
    && unzip /app/xray-bin/xray.zip -d /app/xray-bin/ \
    && find /app/xray-bin -type f -name 'xray' -exec mv {} /app/xray-bin/xray \; \
    && chmod +x /app/xray-bin/xray \
    && rm -rf /app/xray-bin/xray.zip /app/xray-bin/Xray-linux-64*

COPY pyproject.toml .
COPY uv.lock .

RUN uv sync

COPY static ./static
COPY templates ./templates
COPY core.py .
COPY db_utils.py .
COPY app.py .

# Expose port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0

# Run the app
CMD ["uv", "run", "python", "app.py"]
