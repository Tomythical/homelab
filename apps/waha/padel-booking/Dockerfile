FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /app

RUN pip install --no-cache-dir restate_sdk hypercorn

COPY app.py .

CMD ["python", "app.py"]