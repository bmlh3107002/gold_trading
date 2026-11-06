# syntax=docker/dockerfile:1
# Keycloak cho Gold Trading: ghim phiên bản, build tối ưu, kèm file realm (KHÔNG chứa bí mật).
# Bí mật (client secret, mật khẩu) lấy từ biến môi trường lúc chạy.
FROM keycloak/keycloak:26.8.2 AS builder
ENV KC_DB=postgres \
    KC_HTTP_RELATIVE_PATH=/auth \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=false
RUN /opt/keycloak/bin/kc.sh build

FROM keycloak/keycloak:26.8.2
COPY --from=builder /opt/keycloak/ /opt/keycloak/
COPY --chown=keycloak:keycloak realm/gold-trading-realm.json /opt/keycloak/data/import/gold-trading-realm.json
COPY --chown=keycloak:keycloak --chmod=0755 sync-client.sh healthcheck.sh /opt/keycloak/bin/
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start", "--optimized", "--import-realm"]
