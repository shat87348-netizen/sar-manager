#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

SCAN_LOG_DIR="${SCRIPT_DIR}/logs"
SCAN_LOG_FILE="${SCAN_LOG_DIR}/scan.log"
SCAN_PID_FILE="${SCAN_LOG_DIR}/scan.pid"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is not installed." >&2
  exit 1
fi

compose() {
  "${COMPOSE[@]}" -f compose.yaml "$@"
}

scanner_nice() {
  local value
  value="$(sed -n 's/^SCANNER_NICE=//p' .env | tail -n 1)"
  if [[ ! "${value:-15}" =~ ^-?[0-9]+$ ]]; then
    echo "Invalid SCANNER_NICE value in .env" >&2
    exit 1
  fi
  echo "${value:-15}"
}

scan_is_running() {
  [[ -f "${SCAN_PID_FILE}" ]] || return 1

  local pid
  pid="$(<"${SCAN_PID_FILE}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" 2>/dev/null
}

case "${1:-help}" in
  start)   compose up -d --no-build ;;
  stop)    compose stop ;;
  restart) compose restart ;;
  status)  compose ps ;;
  logs)    compose logs -f --tail=200 api db ;;
  # scanner 是独立容器，默认仅使用 1 个 CPU，且以较低优先级运行。
  scan)    compose run --rm scanner ;;
  scan-bg)
    if scan_is_running; then
      echo "Scan is already running (PID $(<"${SCAN_PID_FILE}"))."
      exit 1
    fi
    mkdir -p "${SCAN_LOG_DIR}"
    rm -f "${SCAN_PID_FILE}"
    printf '\n===== scan started: %s =====\n' "$(date '+%F %T')" >> "${SCAN_LOG_FILE}"
    nohup "$0" scan >> "${SCAN_LOG_FILE}" 2>&1 < /dev/null &
    echo "$!" > "${SCAN_PID_FILE}"
    echo "Scan started in background (PID $!)."
    echo "Log file: ${SCAN_LOG_FILE}"
    ;;
  scan-status)
    if scan_is_running; then
      echo "Scan is running (PID $(<"${SCAN_PID_FILE}"))."
    else
      echo "No background scan is running."
    fi
    ;;
  scan-logs) tail -f -- "${SCAN_LOG_FILE}" ;;
  scan-force)
    compose run --rm --entrypoint nice scanner -n "$(scanner_nice)" python -m app.cli scan /data --force
    ;;
  ingest)
    shift
    [[ "$#" -eq 1 ]] || {
      echo "Usage: $0 ingest <path-below-upload>" >&2
      exit 1
    }
    compose run --rm --entrypoint nice scanner -n "$(scanner_nice)" python -m app.cli ingest -- "$1"
    ;;
  ingest-force)
    shift
    [[ "$#" -eq 1 ]] || {
      echo "Usage: $0 ingest-force <path-below-upload>" >&2
      exit 1
    }
    compose run --rm --entrypoint nice scanner -n "$(scanner_nice)" python -m app.cli ingest --force -- "$1"
    ;;
  data-dir) "${SCRIPT_DIR}/configure-data-dir.sh" --show ;;
  set-data-dir)
    shift
    "${SCRIPT_DIR}/configure-data-dir.sh" "${1:-}"
    ;;
  health)
    API_PORT="$(sed -n 's/^SAR_API_PORT=//p' .env | tail -n 1)"
    curl --fail --show-error "http://127.0.0.1:${API_PORT:-8000}/health"
    echo
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs|scan|scan-bg|scan-status|scan-logs|scan-force|ingest|ingest-force|health|data-dir|set-data-dir [DIRECTORY]}"
    exit 1
    ;;
esac
