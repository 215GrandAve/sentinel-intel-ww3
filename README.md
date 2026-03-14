# Sentinel / WW3 Barometer v4.0

Final production build. JSON-driven dashboard with full theological, military, financial, and geopolitical vector scoring.

## What changed from v3

- CSS tightened back to original war-room intensity — denser spacing, sharper borders, restored glow effects and alert pulse animation
- JS rewritten clean — removed hacky React fragment handling from axis chain, simplified all render functions
- Intel card language restored to original directness — specific names, specific numbers, specific claims
- All display properties verified — doctrine-grid, intel-grid, change-strip, market-sections all render correctly
- Mobile breakpoints polished — tested at 375px, 720px, 960px
- Version bumped to v4.0 across all files

## Local preview

```bash
python -m http.server 8000
```

Then open `http://localhost:8000/public/index.html`

## Draft/publish flow

Draft a proposal:
```bash
python backend/update.py --review-packet data/review_packet.sample.json
```

With Claude API:
```bash
ANTHROPIC_API_KEY=sk-xxx python backend/update.py --provider anthropic --review-packet data/review_packet.sample.json
```

Promote after review:
```bash
python backend/publish.py
```

## Deploy to Hetzner

1. Get a CX22 at hetzner.com ($4.50/month)
2. SSH in, install nginx + python3
3. Clone this repo to /var/www/sentinel
4. Point nginx root to /var/www/sentinel/public
5. Set up cron: `0 6,18 * * * cd /var/www/sentinel && python3 backend/update.py --provider anthropic`
6. Point your domain DNS to the server IP via Cloudflare
