FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin contamind

COPY requirements.txt ./
RUN python -m pip install -r requirements.txt

COPY . ./
RUN chmod 0555 /app/docker/entrypoint.sh

USER contamind

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
