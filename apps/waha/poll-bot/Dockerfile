FROM python:3.14-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn httpx restate-sdk

RUN groupadd -r appgroup && useradd -r -g appgroup -u 1000 appuser

COPY app.py .

RUN mkdir -p /data && chown -R appuser:appgroup /data /app

USER appuser

EXPOSE 8000 9080

CMD ["python", "app.py"]