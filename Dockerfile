# SupplyChain IQ: single-container image (Frappe v16 + supplychain_iq) for Render or any Docker host.
# Runtime pieces: gunicorn (web), a local Redis (cache/queue), optional worker+scheduler.
# Database: external PostgreSQL (e.g. Neon), configured through environment variables.

FROM python:3.14-slim-trixie

ARG FRAPPE_BRANCH=version-16
ARG NODE_MAJOR=24

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH=/home/frappe/.local/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates xz-utils build-essential pkg-config \
        libmariadb-dev libpq-dev postgresql-client redis-server cron \
        libffi-dev libjpeg62-turbo-dev zlib1g-dev fonts-dejavu-core \
    && NODE_VERSION=$(curl -fsSL https://nodejs.org/dist/latest-v${NODE_MAJOR}.x/ | grep -oE "node-v${NODE_MAJOR}\.[0-9]+\.[0-9]+-linux-x64\.tar\.xz" | head -1) \
    && curl -fsSL "https://nodejs.org/dist/latest-v${NODE_MAJOR}.x/${NODE_VERSION}" | tar -xJ -C /usr/local --strip-components=1 \
    && npm install -g yarn \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash frappe

USER frappe
WORKDIR /home/frappe

RUN pip install --user --no-cache-dir uv \
    && uv tool install frappe-bench \
    && bench init frappe-bench \
        --frappe-branch ${FRAPPE_BRANCH} \
        --python /usr/local/bin/python3.14 \
        --skip-redis-config-generation \
        --no-backups \
        --verbose

WORKDIR /home/frappe/frappe-bench

COPY --chown=frappe:frappe . apps/supplychain_iq
RUN rm -rf apps/supplychain_iq/.git \
    && uv pip install --python ./env/bin/python -e apps/supplychain_iq \
    && printf "frappe\nsupplychain_iq\n" > sites/apps.txt \
    && bench build --production \
    && rm -rf ~/.cache

EXPOSE 8000
ENTRYPOINT ["/home/frappe/frappe-bench/apps/supplychain_iq/deploy/entrypoint.sh"]
