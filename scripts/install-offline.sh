#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

case "$(uname -m)" in
  x86_64|amd64) ;;
  *)
    echo "Unsupported architecture: $(uname -m). This bundle is for CentOS 7 x86_64." >&2
    exit 1
    ;;
esac

command -v docker >/dev/null 2>&1 || {
  echo "Docker is not installed. Install Docker Engine 20.10+ first." >&2
  exit 1
}

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is not installed. Install the Compose plugin or docker-compose 1.29+." >&2
  exit 1
fi

docker info >/dev/null 2>&1 || {
  echo "Cannot access Docker. Start Docker and run this script as a permitted user." >&2
  exit 1
}

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created ${SCRIPT_DIR}/.env"
  echo "Edit SAR_DATA_DIR and POSTGRES_PASSWORD, then run ./install.sh again."
  exit 1
fi

if grep -q '^POSTGRES_PASSWORD=replace-with-a-strong-password$' .env; then
  echo "Set a strong POSTGRES_PASSWORD in .env before installation." >&2
  exit 1
fi

if [[ -f SHA256SUMS ]]; then
  sha256sum -c SHA256SUMS
fi

echo "Loading offline Docker images..."
docker load -i sar-manager-images.tar.gz
"${COMPOSE[@]}" -f compose.yaml up -d --no-build
"${COMPOSE[@]}" -f compose.yaml ps

API_PORT="$(sed -n 's/^SAR_API_PORT=//p' .env | tail -n 1)"
API_PORT="${API_PORT:-8000}"
echo "SAR Manager: http://SERVER_IP:${API_PORT}/"
echo "Data directory: ./manage.sh data-dir"
echo "Change it later: ./manage.sh set-data-dir /path/to/sar-data"
echo "Run './manage.sh scan' to scan the configured SAR_DATA_DIR."
