# YooKassa mock: the payment gateway is outside the system (CLAUDE.md, "Локальная среда"),
# so locally a small service plays its part by the same API v3 contract.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8100
CMD ["uvicorn", "mock.main:app", "--host", "0.0.0.0", "--port", "8100"]
