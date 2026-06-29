FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

WORKDIR /app

RUN pip install --no-cache-dir restate_sdk fastapi uvicorn playwright

COPY app.py .

CMD ["python", "app.py"]