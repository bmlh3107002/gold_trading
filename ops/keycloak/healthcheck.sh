#!/bin/bash
# Image Keycloak không có curl: gọi /health/ready ở cổng quản trị 9000 bằng /dev/tcp.
exec 3<>/dev/tcp/127.0.0.1/9000 || exit 1
printf 'GET /auth/health/ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' >&3
head -n 1 <&3 | grep -q ' 200 '
