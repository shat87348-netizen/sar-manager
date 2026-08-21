#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_INSTALL_ROOT="${APP_INSTALL_ROOT:-/opt}"

die() {
  echo "错误：$*" >&2
  exit 1
}

if [[ "${EUID}" -ne 0 ]]; then
  die "请使用 root 运行：sudo ./install-all.sh"
fi

case "$(uname -m)" in
  x86_64|amd64) ;;
  *) die "此离线包只支持 x86-64，当前架构为 $(uname -m)" ;;
esac

command -v rpm >/dev/null 2>&1 || die "没有找到 rpm；目标机器必须是 CentOS 7"
command -v yum >/dev/null 2>&1 || die "没有找到 yum；目标机器必须是 CentOS 7"
command -v systemctl >/dev/null 2>&1 || die "目标机器必须使用 systemd"
command -v sha256sum >/dev/null 2>&1 || die "没有找到 sha256sum"

RHEL_MAJOR="$(rpm -E '%{?rhel}' 2>/dev/null || true)"
[[ "${RHEL_MAJOR}" == "7" ]] || {
  die "此包只支持 CentOS/RHEL 7，当前 rhel 标识为 '${RHEL_MAJOR:-未知}'"
}

APP_ARCHIVES=("${SCRIPT_DIR}"/app/sar-manager-offline-*-centos7-amd64.tar.gz)
if [[ "${#APP_ARCHIVES[@]}" -ne 1 || ! -f "${APP_ARCHIVES[0]}" ]]; then
  die "app 目录必须且只能包含一个 SAR Manager 离线应用包"
fi
APP_ARCHIVE="${APP_ARCHIVES[0]}"
APP_BUNDLE_NAME="$(basename "${APP_ARCHIVE}" .tar.gz)"
APP_DIR="${APP_INSTALL_ROOT}/${APP_BUNDLE_NAME}"

[[ -f "${SCRIPT_DIR}/SHA256SUMS" ]] || die "缺少 SHA256SUMS"
[[ -d "${SCRIPT_DIR}/rpms" ]] || die "缺少 rpms 目录"
[[ -d "${SCRIPT_DIR}/keys" ]] || die "缺少 keys 目录"

echo "[1/6] 校验全部离线资源……"
(
  cd "${SCRIPT_DIR}"
  sha256sum -c SHA256SUMS
)

echo "[2/6] 导入 RPM 签名密钥……"
rpm --import "${SCRIPT_DIR}/keys/RPM-GPG-KEY-CentOS-7"
rpm --import "${SCRIPT_DIR}/keys/RPM-GPG-KEY-Docker"

echo "[3/6] 验证 RPM 签名……"
for package in "${SCRIPT_DIR}"/rpms/*.rpm; do
  rpm -K "${package}" >/dev/null || die "RPM 校验失败：${package}"
done

conflicts=()
for package in \
  docker docker-client docker-client-latest docker-common docker-latest \
  docker-latest-logrotate docker-logrotate docker-engine podman-docker
do
  if rpm -q "${package}" >/dev/null 2>&1; then
    conflicts+=("${package}")
  fi
done
if ((${#conflicts[@]})); then
  die "检测到冲突的软件包：${conflicts[*]}。请让管理员确认后处理"
fi

echo "[4/6] 完全离线安装 Docker Engine、Compose 及依赖……"
YUM_REPO_DIR="$(mktemp -d /tmp/sar-offline-yum.XXXXXX)"
cleanup_yum_repo() {
  rm -rf "${YUM_REPO_DIR}"
}
trap cleanup_yum_repo EXIT

cat > "${YUM_REPO_DIR}/sar-offline.repo" <<EOF
[sar-offline]
name=SAR Manager CentOS 7 offline packages
baseurl=file://${SCRIPT_DIR}/rpms
enabled=1
gpgcheck=1
repo_gpgcheck=0
gpgkey=file://${SCRIPT_DIR}/keys/RPM-GPG-KEY-CentOS-7
       file://${SCRIPT_DIR}/keys/RPM-GPG-KEY-Docker
metadata_expire=-1
EOF

yum -y \
  --setopt="reposdir=${YUM_REPO_DIR}" \
  --disablerepo='*' \
  --enablerepo='sar-offline' \
  localinstall \
  "${SCRIPT_DIR}/rpms/containerd.io-1.6.33-3.1.el7.x86_64.rpm" \
  "${SCRIPT_DIR}/rpms/docker-ce-20.10.24-3.el7.x86_64.rpm" \
  "${SCRIPT_DIR}/rpms/docker-ce-cli-20.10.24-3.el7.x86_64.rpm" \
  "${SCRIPT_DIR}/rpms/docker-compose-plugin-2.27.1-1.el7.x86_64.rpm"

echo "[5/6] 启用并启动 Docker……"
systemctl daemon-reload
systemctl enable docker
systemctl start docker
docker info >/dev/null
docker compose version

echo "[6/6] 准备 SAR Manager 应用……"
mkdir -p "${APP_INSTALL_ROOT}"
if [[ -e "${APP_DIR}" ]]; then
  echo "应用目录已经存在，保留：${APP_DIR}"
else
  tar -xzf "${APP_ARCHIVE}" -C "${APP_INSTALL_ROOT}"
fi

if [[ ! -f "${APP_DIR}/.env" ]]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
fi

cat <<EOF

离线依赖安装完成，应用目录：
  ${APP_DIR}

下一步：
  vi ${APP_DIR}/.env
  cd ${APP_DIR}
  ./install.sh
  ./manage.sh health
  ./manage.sh scan

浏览器访问：http://服务器IP:8000/web/
EOF
