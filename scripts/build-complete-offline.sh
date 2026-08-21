#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSION="${SAR_MANAGER_VERSION:-0.2.4}"
OFFLINE_DIR="${PROJECT_DIR}/offline"
APP_ARCHIVE="${PROJECT_DIR}/sar-manager-offline-${VERSION}-centos7-amd64.tar.gz"
APP_BUNDLE_DIR="${PROJECT_DIR}/sar-manager-offline-${VERSION}-centos7-amd64"

[[ "$(dirname "${OFFLINE_DIR}")" == "${PROJECT_DIR}" ]] || {
  echo "Refusing unexpected offline path: ${OFFLINE_DIR}" >&2
  exit 1
}
[[ "$(basename "${OFFLINE_DIR}")" == "offline" ]] || {
  echo "Refusing unexpected offline directory name" >&2
  exit 1
}
[[ -d "${OFFLINE_DIR}/rpms" ]] || {
  echo "Existing offline/rpms dependency snapshot is required." >&2
  exit 1
}
[[ -d "${OFFLINE_DIR}/keys" ]] || {
  echo "Existing offline/keys is required." >&2
  exit 1
}

if [[ -f "${OFFLINE_DIR}/SHA256SUMS" ]]; then
  echo "Verifying existing CentOS 7 dependency snapshot..."
  (
    cd "${OFFLINE_DIR}"
    sha256sum -c SHA256SUMS >/dev/null
  )
fi

echo "Building application Docker bundle..."
SAR_MANAGER_VERSION="${VERSION}" "${SCRIPT_DIR}/build-offline-bundle.sh"
[[ -f "${APP_ARCHIVE}" ]] || {
  echo "Application archive was not created: ${APP_ARCHIVE}" >&2
  exit 1
}

STAGING_ROOT="$(mktemp -d "${PROJECT_DIR}/.complete-offline.XXXXXX")"
trap 'rm -rf "${STAGING_ROOT}"' EXIT
STAGING="${STAGING_ROOT}/offline"
mkdir -p "${STAGING}/app"

echo "Copying verified CentOS 7 and Docker dependencies..."
cp -R "${OFFLINE_DIR}/rpms" "${STAGING}/rpms"
cp -R "${OFFLINE_DIR}/keys" "${STAGING}/keys"
cp "${OFFLINE_DIR}/PACKAGE_MANIFEST.txt" "${STAGING}/PACKAGE_MANIFEST.txt"
cp "${APP_ARCHIVE}" "${STAGING}/app/"
cp "${SCRIPT_DIR}/install-all.sh" "${STAGING}/install-all.sh"
cp "${PROJECT_DIR}/COMPLETE_OFFLINE_DEPLOY.md" "${STAGING}/README.md"
chmod +x "${STAGING}/install-all.sh"

echo "Generating complete SHA-256 manifest..."
(
  cd "${STAGING}"
  find . -type f ! -name SHA256SUMS -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum > SHA256SUMS
)

echo "Replacing offline directory..."
rm -rf "${OFFLINE_DIR}"
mv "${STAGING}" "${OFFLINE_DIR}"
trap - EXIT
rm -rf "${STAGING_ROOT}"

echo "Removing application build intermediates from project root..."
rm -f "${APP_ARCHIVE}"
rm -rf "${APP_BUNDLE_DIR}"

echo "Created complete offline resource directory:"
du -sh "${OFFLINE_DIR}"
