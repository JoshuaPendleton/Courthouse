# CPU-only developer image. See README for CPU/GPU and resource constraints.
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake && rm -rf /var/lib/apt/lists/*
COPY requirements-inference.txt ./
RUN python -m pip install --no-cache-dir -r requirements-inference.txt
COPY . .
ENV COURTHOUSE_HOST=0.0.0.0 COURTHOUSE_PORT=8050 COURTHOUSE_PRELOAD_AGENTS=1
EXPOSE 8050
CMD ["python","server.py"]
