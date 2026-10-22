# ECO de prueba · imagen para Cloud Run.
# Se construye desde la raíz del repositorio:
#   docker build -f plataforma/eco/Dockerfile --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/plataforma \
    ECO_REGISTRO=""

WORKDIR /app
COPY plataforma/eco/requirements.txt plataforma/eco/requirements.txt
RUN pip install --no-cache-dir -r plataforma/eco/requirements.txt

COPY herramientas/ herramientas/
COPY clientes/ clientes/
COPY plataforma/ plataforma/

ARG GIT_COMMIT=""
ENV GIT_COMMIT=${GIT_COMMIT}

# Claude Code no debe correr como administrador del contenedor.
RUN useradd --create-home eco
USER eco

CMD exec uvicorn eco.servicio:app --host 0.0.0.0 --port ${PORT:-8080}
