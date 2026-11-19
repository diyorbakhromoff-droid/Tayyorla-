#!/usr/bin/env bash
# Avtomatik yangilanish holati: bash /opt/tayyorla/scripts/autodeploy-status.sh
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "== Taymer"
systemctl list-timers tayyorla-autodeploy.timer --no-pager 2>/dev/null | head -n 3
echo
echo "== Serverdagi versiya"
git -C "$APP_DIR" log -1 --format='%h  %s  (%cr)'
echo
echo "== Oxirgi yozuvlar (/var/log/tayyorla-autodeploy.log)"
tail -n 25 /var/log/tayyorla-autodeploy.log 2>/dev/null || echo "hali yozuv yo'q"
echo
echo "== Konteynerlar"
cd "$APP_DIR" && docker compose ps
