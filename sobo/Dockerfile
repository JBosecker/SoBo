# Basis-Image direkt im Dockerfile (build.yaml ist seit der BuildKit-Umstellung
# von Home Assistant abgekündigt). Multi-Arch: amd64 und aarch64.
ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.13-alpine3.24
FROM ${BUILD_FROM}

# git wird nur für die gepinnte SoCo-Fork-Abhängigkeit beim Build benötigt.
COPY backend /opt/sobo/backend
RUN apk add --no-cache --virtual .build-deps git \
    && pip install --no-cache-dir /opt/sobo/backend \
    && apk del .build-deps \
    && rm -rf /opt/sobo/backend/tests

COPY rootfs /
RUN chmod a+x /etc/services.d/sobo/run /etc/services.d/sobo/finish

WORKDIR /data

LABEL \
    org.opencontainers.image.title="SoBo" \
    org.opencontainers.image.description="Sonos-Jukebox als Home Assistant App" \
    org.opencontainers.image.source="https://github.com/JBosecker/SoBo" \
    org.opencontainers.image.licenses="MIT"
