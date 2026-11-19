#!/usr/bin/env bash
# Avtomatik yangilanishni yoqish (bir marta): bash /opt/tayyorla/scripts/autodeploy-install.sh
# systemd taymeri har 2 daqiqada scripts/autodeploy.sh ni ishga tushiradi.
set -e
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
chmod +x "$APP_DIR/scripts/autodeploy.sh"
git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true

cat > /etc/systemd/system/tayyorla-autodeploy.service <<EOF
[Unit]
Description=Tayyorla avtomatik yangilanish (git pull + docker compose up --build)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
Environment=APP_DIR=$APP_DIR
ExecStart=$APP_DIR/scripts/autodeploy.sh
TimeoutStartSec=1800
EOF

cat > /etc/systemd/system/tayyorla-autodeploy.timer <<EOF
[Unit]
Description=Tayyorla avtomatik yangilanish — har 2 daqiqada

[Timer]
OnBootSec=1min
OnUnitActiveSec=2min
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now tayyorla-autodeploy.timer
systemctl start tayyorla-autodeploy.service || true

echo
echo "Avtomatik yangilanish yoqildi: har 2 daqiqada GitHub tekshiriladi."
echo "Holat:     bash $APP_DIR/scripts/autodeploy-status.sh"
echo "O'chirish: bash $APP_DIR/scripts/autodeploy-uninstall.sh"
