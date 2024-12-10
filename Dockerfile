FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data directory and set permissions
RUN mkdir -p /app/data && chmod 777 /app/data

VOLUME ["/app/data"]

CMD ["python", "main.py"] 