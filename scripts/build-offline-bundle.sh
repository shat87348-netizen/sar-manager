#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSION="${SAR_MANAGER_VERSION:-0.2.4}"
BUNDLE_NAME="sar-manager-offline-${VERSION}-centos7-amd64"
BUNDLE_DIR="${PROJECT_DIR}/${BUNDLE_NAME}"
ARCHIVE_PATH="${PROJECT_DIR}/${BUNDLE_NAME}.tar.gz"
PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"
POSTGIS_IMAGE="${POSTGIS_IMAGE:-postgis/postgis:16-3.5}"
API_IMAGE="${SAR_API_IMAGE:-sar-manager-api:${VERSION}}"
PYTHON_BASE_IMAGE="${PYTHON_BASE_IMAGE:-python:3.12-slim}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"

cd "${PROJECT_DIR}"

if [[ "${PLATFORM}" != "linux/amd64" ]]; then
  echo "This CentOS 7 bundle must be built for linux/amd64." >&2
  exit 1
fi

command -v docker >/dev/null 2>&1 || {
  echo "Docker is required to build the offline bundle." >&2
  exit 1
}

docker info >/dev/null
docker buildx version >/dev/null

if [[ "${SKIP_API_BUILD:-0}" == "1" ]]; then
  echo "Using prebuilt ${API_IMAGE}."
  docker image inspect "${API_IMAGE}" >/dev/null
else
  echo "Building ${API_IMAGE} for ${PLATFORM}..."
  docker buildx build \
    --platform "${PLATFORM}" \
    --build-arg "BASE_IMAGE=${PYTHON_BASE_IMAGE}" \
    --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" \
    --load \
    -t "${API_IMAGE}" \
    .
fi

if [[ "$(docker image inspect "${POSTGIS_IMAGE}" --format '{{.Architecture}}' 2>/dev/null || true)" != "amd64" ]]; then
  docker pull --platform "${PLATFORM}" "${POSTGIS_IMAGE}"
else
  echo "Using cached ${POSTGIS_IMAGE} linux/amd64 image."
fi

API_ARCH="$(docker image inspect "${API_IMAGE}" --format '{{.Architecture}}')"
POSTGIS_ARCH="$(docker image inspect "${POSTGIS_IMAGE}" --format '{{.Architecture}}')"
if [[ "${API_ARCH}" != "amd64" || "${POSTGIS_ARCH}" != "amd64" ]]; then
  echo "Image architecture check failed: api=${API_ARCH}, postgis=${POSTGIS_ARCH}" >&2
  exit 1
fi

STAGING_DIR="$(mktemp -d "${PROJECT_DIR}/.offline-bundle.XXXXXX")"
trap 'rm -rf "${STAGING_DIR}"' EXIT
STAGING_BUNDLE="${STAGING_DIR}/${BUNDLE_NAME}"
mkdir -p "${STAGING_BUNDLE}"

echo "Exporting Docker images..."
docker save "${API_IMAGE}" "${POSTGIS_IMAGE}" | gzip -1 > "${STAGING_BUNDLE}/sar-manager-images.tar.gz"

cp compose.offline.yaml "${STAGING_BUNDLE}/compose.yaml"
awk -v image="${API_IMAGE}" '
  /^SAR_API_IMAGE=/ { print "SAR_API_IMAGE=" image; next }
  { print }
' .env.example > "${STAGING_BUNDLE}/.env.example"
cp scripts/install-offline.sh "${STAGING_BUNDLE}/install.sh"
cp scripts/manage-offline.sh "${STAGING_BUNDLE}/manage.sh"
cp scripts/configure-data-dir.sh "${STAGING_BUNDLE}/configure-data-dir.sh"
cp OFFLINE_DEPLOY.md "${STAGING_BUNDLE}/README.md"
chmod +x "${STAGING_BUNDLE}/install.sh" "${STAGING_BUNDLE}/manage.sh" "${STAGING_BUNDLE}/configure-data-dir.sh"

(
  cd "${STAGING_BUNDLE}"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum sar-manager-images.tar.gz compose.yaml install.sh manage.sh configure-data-dir.sh > SHA256SUMS
  else
    shasum -a 256 sar-manager-images.tar.gz compose.yaml install.sh manage.sh configure-data-dir.sh > SHA256SUMS
  fi
)

rm -rf "${BUNDLE_DIR}"
mv "${STAGING_BUNDLE}" "${BUNDLE_DIR}"
tar -C "${PROJECT_DIR}" -czf "${ARCHIVE_PATH}" "${BUNDLE_NAME}"

echo "Created ${ARCHIVE_PATH}"
ls -lh "${ARCHIVE_PATH}"
