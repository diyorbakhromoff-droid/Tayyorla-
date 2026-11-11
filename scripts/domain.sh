#!/bin/sh
# Domenni ulaydi: DNS tekshiriladi, .env dagi BASE_URL va SITE_ADDRESS yangilanadi, Caddy va ilova qayta ishga tushadi.
# Eski manzil (masalan 77-42-80-83.sslip.io) ham ishlashda davom etadi — avval yuborilgan havolalar buzilmaydi.
# Ishlatish: sh scripts/domain.sh tayyorlaai.uz
set -e
cd "$(dirname "$0")/.."
D="$1"
if [ -z "$D" ]; then echo "Domen nomini yozing: sh scripts/domain.sh tayyorlaai.uz"; exit 1; fi
IP=$(curl -s -4 --max-time 10 https://api.ipify.org || true)
for h in "$D" "www.$D"; do
  got=$(getent ahostsv4 "$h" | awk 'NR==1{print $1}')
  if [ -z "$got" ]; then echo "XATO: $h hali hech qayerga qaramayapti. DNS da A yozuv qo'shing va 10-30 daqiqa kuting."; exit 1; fi
  if [ -n "$IP" ] && [ "$got" != "$IP" ]; then echo "XATO: $h -> $got, lekin server IP si $IP. DNS dagi A yozuvni tekshiring."; exit 1; fi
  echo "OK: $h -> $got"
done
touch .env
OLD=$(grep '^SITE_ADDRESS=' .env | head -1 | cut -d= -f2-)
KEEP=""
for a in $OLD; do
  case "$a" in "$D"|"www.$D"|:80|"") ;; *) KEEP="$KEEP $a" ;; esac
done
sed -i '/^BASE_URL=/d;/^SITE_ADDRESS=/d' .env
echo "BASE_URL=https://$D" >> .env
echo "SITE_ADDRESS=$D www.$D$KEEP" >> .env
echo "Yozildi: BASE_URL=https://$D"
echo "Yozildi: SITE_ADDRESS=$D www.$D$KEEP"
docker compose up -d --force-recreate caddy app
echo "Tayyor. 1-2 daqiqadan keyin https://$D ni oching (sertifikat avtomatik olinadi)."
