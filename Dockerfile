FROM python:3.12-slim
WORKDIR /app
# Stdlib only: nothing to pip install. .dockerignore keeps .env, runtime/, logs/ and .git out.
COPY . /app
RUN mkdir -p /app/runtime /app/logs
ENV PYTHONUNBUFFERED=1 \
    SAMPLE_MODE=true \
    PORT=8000 \
    HOST=0.0.0.0 \
    RESCUE_OPEN_RUN=true
# Inside the container the server must listen on all interfaces for -p 8000:8000 to work; on a host it defaults to 127.0.0.1.
# RESCUE_OPEN_RUN=true lets clients outside the container call POST /run only (other POSTs still need loopback or a token);
# setting RESCUE_OPERATOR_TOKEN (or -e RESCUE_OPEN_RUN=false) closes it again.
EXPOSE 8000
# SAMPLE_MODE=true needs no Zetaris, Nightshift or network. For connected mode pass
# --env-file .env -e SAMPLE_MODE=false and host.docker.internal endpoints (see README).
CMD ["python", "run.py", "serve"]
