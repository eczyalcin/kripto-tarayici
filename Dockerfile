# 7/24 çalıştırma için konteyner imajı.
# Raspberry Pi (arm64), Linux VPS (amd64) ve Docker Desktop'ta aynı şekilde çalışır.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Istanbul

WORKDIR /app

# Önce sadece bağımlılıklar: kod değişince katman yeniden kurulmasın
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Kök kullanıcı olarak çalışmasın
RUN useradd -m -u 1000 kripto \
    && mkdir -p /app/data /app/logs /app/reports \
    && chown -R kripto:kripto /app
USER kripto

EXPOSE 8501

# Sağlık kontrolü: panel ayakta mı?
HEALTHCHECK --interval=60s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=5).status==200 else 1)" \
        || exit 1

CMD ["python", "run.py", "serve", "--lan", "--no-browser"]
