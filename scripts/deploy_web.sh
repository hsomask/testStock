#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
DAY="${1:-}"
if [[ ! "$DAY" =~ ^[0-9]{8}$ ]]; then
    echo "Usage: bash scripts/deploy_web.sh YYYYMMDD (expected completed report date)" >&2
    exit 2
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Tracked files have local edits; review them before deploying a tagged release." >&2
    exit 2
fi
command -v docker >/dev/null
docker compose version >/dev/null
docker info >/dev/null
test -f "reports/daily/daily_summary_${DAY}.json" || { echo "Expected summary missing" >&2; exit 2; }
test -f "reports/daily/trade_plan_${DAY}.json" || { echo "Expected trade plan missing" >&2; exit 2; }
mkdir -p reports/events logs

REVISION="$(git rev-parse --short=12 HEAD)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
export WEB_IMAGE="stock-review-web:${REVISION}-${STAMP}"
COMPOSE=(docker compose -f compose.web.yml)
"${COMPOSE[@]}" config --quiet
OLD_CONTAINER="$("${COMPOSE[@]}" ps -q stock-web)"
ROLLBACK_IMAGE=""
if [[ -n "$OLD_CONTAINER" ]]; then
    OLD_IMAGE="$(docker inspect --format '{{.Image}}' "$OLD_CONTAINER")"
    ROLLBACK_IMAGE="stock-review-web:rollback-${STAMP}"
    docker image tag "$OLD_IMAGE" "$ROLLBACK_IMAGE"
fi
"${COMPOSE[@]}" build stock-web

# A failed release never stops the independent report/DB/lawyer services.
rollback() {
    echo "Release failed. Restoring the previous web image, if present." >&2
    if [[ -n "$ROLLBACK_IMAGE" ]]; then
        WEB_IMAGE="$ROLLBACK_IMAGE" "${COMPOSE[@]}" up -d --no-build --no-deps stock-web || true
    else
        "${COMPOSE[@]}" stop stock-web || true
    fi
}
trap rollback ERR
"${COMPOSE[@]}" up -d --no-build --no-deps stock-web
CONTAINER="$("${COMPOSE[@]}" ps -q stock-web)"
HEALTH=""
for _ in $(seq 1 30); do
    HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$CONTAINER")"
    [[ "$HEALTH" == "healthy" ]] && break
    sleep 2
done
[[ "$HEALTH" == "healthy" ]]
"${COMPOSE[@]}" exec -T stock-web python -m analysis.web_review_smoke --date "$DAY"
trap - ERR
{
    printf 'revision=%s\nimage=%s\nrollback_image=%s\nreport_date=%s\n' "$REVISION" "$WEB_IMAGE" "$ROLLBACK_IMAGE" "$DAY"
} > "logs/web-release-${STAMP}.txt"
echo "Local container and data checks passed. Public network access still needs verification."
echo "Release image: $WEB_IMAGE"
if [[ -n "$ROLLBACK_IMAGE" ]]; then
    echo "Rollback: WEB_IMAGE=$ROLLBACK_IMAGE docker compose -f compose.web.yml up -d --no-build --no-deps stock-web"
fi
