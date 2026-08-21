ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY web ./web

RUN pip install --index-url "${PIP_INDEX_URL}" --no-cache-dir . \
    && useradd --create-home --uid 10001 sar

USER sar

EXPOSE 8000

CMD ["sh", "-c", "python -m app.cli init-db --wait 120 && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
