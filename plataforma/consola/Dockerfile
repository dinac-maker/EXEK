# Consola Exek · imagen para Cloud Run (detrás de IAP).
# Se construye desde la raíz del repositorio:
#   docker build -f plataforma/consola/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/plataforma

WORKDIR /app
COPY plataforma/consola/requirements.txt plataforma/consola/requirements.txt
RUN pip install --no-cache-dir -r plataforma/consola/requirements.txt

COPY herramientas/ herramientas/
COPY plataforma/registro/ plataforma/registro/
COPY plataforma/consola/ plataforma/consola/

RUN useradd --create-home consola
USER consola

CMD exec uvicorn consola.app:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips "*"
