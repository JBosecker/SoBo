ARG BUILD_FROM
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
