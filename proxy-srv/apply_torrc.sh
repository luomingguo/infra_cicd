#!/usr/bin/env bash
set -euo pipefail

TORRC="/etc/tor/torrc"
BACKUP="/etc/tor/torrc.bak.$(date +%s)"

echo "[+] Backing up current torrc -> $BACKUP"
cp "$TORRC" "$BACKUP"

echo "[+] Writing new torrc..."

cat > "$TORRC" <<'EOF'
SocksPort 9050
DataDirectory /var/lib/tor

############################
# 网络调优（可选）
############################
MaxCircuitDirtiness 60
NewCircuitPeriod 30

############################
# 可选优化（稳定性）
############################
ClientOnly 1
AvoidDiskWrites 1

############################
# 代理（注意：Tor官方只对部分PT生效）
############################
HTTPSProxy 127.0.0.1:10808

UseBridges 1
ClientTransportPlugin webtunnel exec /usr/local/bin/lyrebird

Bridge webtunnel [2001:db8:43cc:d277:5ba1:dcd1:516e:d983]:443 AD62C15FAC9C8695F41F4BB5D1F16373F906177F url=https://mitch.pmvl.eu/r9mZqSFwOHSQATtQoPWwZQk9 version=0.0.1

Log info
EOF

echo "[+] Validating config..."
sudo -u debian-tor tor --verify-config -f "$TORRC"

echo "[+] Restarting tor..."
systemctl restart tor@default

echo "[✓] Done"