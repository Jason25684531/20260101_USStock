FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY strategies/requirements.txt /tmp/strategies-requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/strategies-requirements.txt

COPY strategies/ /app/strategies/
COPY utils/ /app/utils/

CMD ["python", "strategies/src/main.py"]
