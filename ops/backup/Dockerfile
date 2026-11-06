# syntax=docker/dockerfile:1
# Sao lưu + khôi phục DB ứng dụng (TimescaleDB) và DB Keycloak (DB-09).
# Dùng đúng image của DB ứng dụng để pg_dump/pg_restore và extension timescaledb cùng phiên bản.
FROM timescale/timescaledb:2.17.2-pg16
COPY --chmod=0755 backup.sh restore.sh common.sh /usr/local/bin/gt/
ENTRYPOINT ["/usr/local/bin/gt/backup.sh"]
CMD ["loop"]
