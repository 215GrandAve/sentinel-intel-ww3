#!/usr/bin/env bash
# ── SENTINEL CRON REFRESH ────────────────────────────────────────────────────
# Runs 3x daily via crontab (6 AM, 12 PM, 8 PM ET).
# 1. Pulls structured API data (markets, GDELT, seismic, etc.)
# 2. Pulls live RSS feeds + sends to Claude for intel synthesis
# 3. Auto-publishes UNLESS theological vectors exceed threshold
# 4. Logs everything
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SITE_DIR="/var/www/sentinel"
VENV="$SITE_DIR/backend/.venv/bin/activate"
LOG="/var/log/sentinel-cron.log"

echo "" >> "$LOG"
echo "══════════════════════════════════════════════════" >> "$LOG"
echo "  SENTINEL UPDATE — $(TZ=America/New_York date)" >> "$LOG"
echo "══════════════════════════════════════════════════" >> "$LOG"

cd "$SITE_DIR"
source "$VENV"

# ── STEP 1: Fetch structured API data (Layer 2) ─────────────────────────────
echo "[1/3] Fetching structured API data (GDELT, markets, seismic, etc.)…" >> "$LOG"
python backend/fetch_apis.py >> "$LOG" 2>&1 || echo "WARN: fetch_apis.py had errors (non-fatal, continuing)" >> "$LOG"

# ── STEP 2: Fetch RSS + generate proposal ────────────────────────────────────
echo "[2/3] Fetching live RSS and generating proposal…" >> "$LOG"
python backend/update.py --live --provider openrouter >> "$LOG" 2>&1
UPDATE_EXIT=$?

if [ $UPDATE_EXIT -ne 0 ]; then
    echo "ERROR: update.py failed with exit code $UPDATE_EXIT" >> "$LOG"
    exit 1
fi

# ── STEP 3: Publish with theological gate ────────────────────────────────────
echo "[3/3] Publishing with theological gate…" >> "$LOG"
python backend/publish.py >> "$LOG" 2>&1
PUBLISH_EXIT=$?

case $PUBLISH_EXIT in
    0)
        echo "✅  AUTO-PUBLISHED successfully." >> "$LOG"
        ;;
    2)
        echo "⚠️  THEOLOGICAL HOLD — awaiting Quik review." >> "$LOG"
        # Uncomment when Telegram bot is wired:
        # curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
        #   -d "chat_id=$QUIK_CHAT_ID" \
        #   -d "text=⚠️ SENTINEL THEOLOGICAL HOLD — review required. Run: python backend/publish.py --force" \
        #   >> "$LOG" 2>&1
        ;;
    *)
        echo "ERROR: publish.py failed with exit code $PUBLISH_EXIT" >> "$LOG"
        ;;
esac

echo "── Done: $(TZ=America/New_York date) ──" >> "$LOG"
