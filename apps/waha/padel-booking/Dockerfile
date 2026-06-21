FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /app

RUN pip install --no-cache-dir restate-sdk

COPY app.py .

CMD ["python", "app.py"]