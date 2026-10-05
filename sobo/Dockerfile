# Base image directly in the Dockerfile (Home Assistant deprecated build.yaml with the
# switch to BuildKit). Multi-arch: amd64 and aarch64.
ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.13-alpine3.24
FROM ${BUILD_FROM}

# git is only needed at build time for the pinned SoCo fork dependency.
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
    org.opencontainers.image.description="Sonos jukebox as a Home Assistant app" \
    org.opencontainers.image.source="https://github.com/JBosecker/SoBo" \
    org.opencontainers.image.licenses="MIT"
