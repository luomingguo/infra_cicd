#!/usr/bin/env bash

set -e

PROXY_ADDR="http://127.0.0.1:10808"

CONF_DIR="/etc/systemd/system/docker.service.d"
CONF_FILE="${CONF_DIR}/http-proxy.conf"

echo "[1/5] 创建目录: ${CONF_DIR}"
sudo mkdir -p "$CONF_DIR"

echo "[2/5] 写入 Docker proxy 配置: ${CONF_FILE}"
sudo tee "$CONF_FILE" > /dev/null <<EOF
[Service]
Environment="HTTP_PROXY=${PROXY_ADDR}/"
Environment="HTTPS_PROXY=${PROXY_ADDR}/"
Environment="NO_PROXY=localhost,127.0.0.1,docker.internal"
EOF

echo "[3/5] 重新加载 systemd"
sudo systemctl daemon-reexec
sudo systemctl daemon-reload

echo "[4/5] 重启 Docker"
sudo systemctl restart docker

echo "[5/5] 验证 proxy 配置"
echo "---- docker info | grep -i proxy ----"
docker info | grep -i proxy || true

echo "---- pull test (busybox) ----"
docker pull busybox

echo "完成"