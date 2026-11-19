#!/usr/bin/env bash
# Avtomatik yangilanishni o'chirish: bash /opt/tayyorla/scripts/autodeploy-uninstall.sh
systemctl disable --now tayyorla-autodeploy.timer 2>/dev/null
rm -f /etc/systemd/system/tayyorla-autodeploy.timer /etc/systemd/system/tayyorla-autodeploy.service
systemctl daemon-reload
echo "Avtomatik yangilanish o'chirildi. Endi yangilash qo'lda: git pull origin main va docker compose up -d --build"
