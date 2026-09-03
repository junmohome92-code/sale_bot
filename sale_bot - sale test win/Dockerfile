FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && playwright install --with-deps chromium

COPY config.example.yaml /app/config.example.yaml

CMD ["python", "-m", "sale_bot.main"]
