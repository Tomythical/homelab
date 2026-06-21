FROM python:3.14-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn httpx

RUN groupadd -r appgroup && useradd -r -g appgroup -u 1000 appuser

COPY app.py .

RUN mkdir -p /data && chown -R appuser:appgroup /data /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]