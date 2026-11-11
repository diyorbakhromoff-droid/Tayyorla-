#!/bin/sh
# ElevenLabs kalitini .env ga yozadi (konsolda Shift belgilari ishlamasa ham bo'ladi).
# Ishlatish: sh scripts/songenv.sh sk-xxxxxxxx   (kalit boshidagi "sk_" ni "sk-" deb yozsangiz ham bo'ladi)
set -e
cd "$(dirname "$0")/.."
if [ -z "$1" ]; then echo "Kalitni yozing: sh scripts/songenv.sh sk-...."; exit 1; fi
KEY=$(printf '%s' "$1" | sed 's/^sk-/sk_/')
touch .env
sed -i '/^ELEVENLABS[_-]API[_-]KEY=/d' .env
printf 'ELEVENLABS_API_KEY=%s\n' "$KEY" >> .env
echo "Tayyor: ElevenLabs kaliti yozildi ($(printf '%s' "$KEY" | cut -c1-6)...)"
