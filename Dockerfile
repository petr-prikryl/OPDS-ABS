FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PUID=1000 \
    PGID=1000

# Install necessary tools for user setup
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies in the final image
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set working directory
WORKDIR /app

# Copy the application code
COPY ./opds_abs ./opds_abs
COPY ./run.py .

# Add entrypoint script
COPY ./docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create data directory with proper permissions
RUN mkdir -p /app/opds_abs/data && \
    chmod 770 /app/opds_abs/data

# Expose port
EXPOSE 8000

# Use the entrypoint script
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "run.py"]
