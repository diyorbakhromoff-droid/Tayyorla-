#!/usr/bin/env bash
# Tayyorla: avtomatik yangilanish. systemd taymeri har 2 daqiqada ishga tushiradi (autodeploy-install.sh o'rnatadi).
# GitHub'dagi main yangilangan bo'lsa: git pull (faqat fast-forward) -> docker compose up -d --build.
# Qurish (build) xato bersa, eski konteynerlar ishlashda davom etadi. Hammasi logga yoziladi.
set -u

APP_DIR="${APP_DIR:-/opt/tayyorla}"
BRANCH="${BRANCH:-main}"
LOG="${LOG:-/var/log/tayyorla-autodeploy.log}"
LOCK="/run/tayyorla-autodeploy.lock"

# log 1 MB dan oshsa, oxirgi qismi qoladi
if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 1048576 ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# bir vaqtda ikkita yangilanish ishlamasin
exec 9>"$LOCK"
flock -n 9 || exit 0

cd "$APP_DIR" || { log "XATO: $APP_DIR topilmadi"; exit 1; }

if ! git fetch -q origin "$BRANCH" 2>>"$LOG"; then
  log "XATO: GitHub'dan yangilanishni olib bo'lmadi (internet yoki ruxsat)"
  exit 1
fi

FAILED="$APP_DIR/.autodeploy-failed"   # oldingi qurish xato bergan bo'lsa — keyingi safar qayta uriniladi
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"
[ "$LOCAL" = "$REMOTE" ] && [ ! -f "$FAILED" ] && exit 0   # yangilik yo'q

# serverda qo'lda o'zgartirilgan kuzatiladigan fayl bo'lsa — ustidan yozmaymiz
if ! git diff --quiet || ! git diff --cached --quiet; then
  log "TO'XTATILDI: serverda qo'lda o'zgartirilgan fayllar bor: $(git diff --name-only | tr '\n' ' ')"
  exit 1
fi

if [ "$LOCAL" != "$REMOTE" ]; then
  log "Yangilanish: ${LOCAL:0:7} -> ${REMOTE:0:7}"
  git log --format='  - %s' "$LOCAL..$REMOTE" >> "$LOG" 2>/dev/null
  if ! git merge -q --ff-only "origin/$BRANCH" >>"$LOG" 2>&1; then
    log "XATO: git merge --ff-only bajarilmadi (tarix ajralgan). Qo'lda tekshiring."
    exit 1
  fi
else
  log "Qayta urinish: oldingi qurish xato bergan edi"
fi

if docker compose up -d --build >>"$LOG" 2>&1; then
  rm -f "$FAILED"
  log "TAYYOR: $(git log -1 --format='%h %s')"
  docker image prune -f >/dev/null 2>&1 || true   # eski image'lar diskni to'ldirmasin
else
  date > "$FAILED"
  log "XATO: docker compose build/up muvaffaqiyatsiz — eski versiya ishlashda davom etadi, 2 daqiqadan keyin qayta uriniladi"
  exit 1
fi
