FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# System deps needed to build some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libssl-dev libffi-dev cargo && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the whole repo (backend imports add_book from repo root)
COPY . /app

ENV PORT 8080
EXPOSE 8080

CMD ["gunicorn", "backend.app:app", "--bind", "0.0.0.0:8080", "--workers", "1"]
