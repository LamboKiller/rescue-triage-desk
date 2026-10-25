FROM python:3.12-slim
WORKDIR /app
# Stdlib only: nothing to pip install. .dockerignore keeps .env, runtime/, logs/ and .git out.
COPY . /app
RUN mkdir -p /app/runtime /app/logs
ENV PYTHONUNBUFFERED=1 \
    SAMPLE_MODE=true \
    PORT=8080
EXPOSE 8080
# SAMPLE_MODE=true needs no Zetaris, Nightshift or network. For connected mode pass
# --env-file .env -e SAMPLE_MODE=false and host.docker.internal endpoints (see README).
CMD ["python", "run.py", "serve"]
