#!/bin/sh
# Click kalitlarini .env ga yozadi (konsolda Shift belgilari ishlamasa ham bo'ladi).
# Ishlatish: sh scripts/clickenv.sh SERVICE_ID MERCHANT_ID MERCHANT_USER_ID SECRET_KEY
set -e
cd "$(dirname "$0")/.."
if [ "$#" -ne 4 ]; then
  echo "4 ta qiymat kerak: service_id merchant_id merchant_user_id secret_key"
  exit 1
fi
touch .env
sed -i '/^CLICK[_-]/d' .env
printf 'CLICK_SERVICE_ID=%s\nCLICK_MERCHANT_ID=%s\nCLICK_MERCHANT_USER_ID=%s\nCLICK_SECRET_KEY=%s\n' "$1" "$2" "$3" "$4" >> .env
echo "Tayyor: .env da $(grep -c '^CLICK_' .env) ta Click qatori bor"
