FROM python:3.12-slim

# Don't buffer stdout/stderr (so logs show up immediately in `docker logs`).
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime config is provided via environment (see .env.example).
CMD ["python", "-u", "bot.py"]
