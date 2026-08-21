#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

ENV_FILE="${SCRIPT_DIR}/.env"
ENV_EXAMPLE="${SCRIPT_DIR}/.env.example"

current_value() {
  if [[ -f "${ENV_FILE}" ]]; then
    sed -n 's/^SAR_DATA_DIR=//p' "${ENV_FILE}" | tail -n 1
  elif [[ -f "${ENV_EXAMPLE}" ]]; then
    sed -n 's/^SAR_DATA_DIR=//p' "${ENV_EXAMPLE}" | tail -n 1
  fi
}

if [[ "${1:-}" == "--show" ]]; then
  CURRENT="$(current_value)"
  echo "当前 SAR 数据目录：${CURRENT:-未配置}"
  if [[ -n "${CURRENT}" ]]; then
    if [[ "${CURRENT}" == /* ]]; then
      RESOLVED="${CURRENT}"
    else
      RESOLVED="${SCRIPT_DIR}/${CURRENT#./}"
    fi
    if [[ -d "${RESOLVED}" ]]; then
      echo "目录状态：存在"
    else
      echo "目录状态：不存在（可以等数据准备好后再配置）"
    fi
  fi
  exit 0
fi

INPUT_DIR="${1:-}"
if [[ -z "${INPUT_DIR}" ]]; then
  echo "当前 SAR 数据目录：$(current_value)"
  printf '请输入新的 SAR/TIFF 数据目录（直接回车取消）：'
  read -r INPUT_DIR
fi

if [[ -z "${INPUT_DIR}" ]]; then
  echo "未修改。"
  exit 0
fi

if [[ "${INPUT_DIR}" == *$'\n'* || "${INPUT_DIR}" == *$'\r'* || "${INPUT_DIR}" == *'$'* || "${INPUT_DIR}" == *'#'* ]]; then
  echo "目录不能包含换行、$ 或 # 字符。" >&2
  exit 1
fi

if [[ "${INPUT_DIR}" != /* ]]; then
  [[ -d "${INPUT_DIR}" ]] || {
    echo "目录不存在：${INPUT_DIR}" >&2
    exit 1
  }
  INPUT_DIR="$(cd "${INPUT_DIR}" && pwd -P)"
fi

[[ -d "${INPUT_DIR}" ]] || {
  echo "目录不存在：${INPUT_DIR}" >&2
  exit 1
}
[[ -r "${INPUT_DIR}" ]] || {
  echo "当前用户无权读取目录：${INPUT_DIR}" >&2
  exit 1
}

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"
fi

TEMP_ENV="$(mktemp "${SCRIPT_DIR}/.env.tmp.XXXXXX")"
trap 'rm -f "${TEMP_ENV}"' EXIT
awk -v value="${INPUT_DIR}" '
  BEGIN { found = 0 }
  /^SAR_DATA_DIR=/ {
    if (!found) {
      print "SAR_DATA_DIR=" value
      found = 1
    }
    next
  }
  { print }
  END {
    if (!found) print "SAR_DATA_DIR=" value
  }
' "${ENV_FILE}" > "${TEMP_ENV}"
chmod 600 "${TEMP_ENV}"
mv "${TEMP_ENV}" "${ENV_FILE}"
trap - EXIT

echo "已配置 SAR 数据目录：${INPUT_DIR}"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    COMPOSE=()
  fi

  if ((${#COMPOSE[@]})); then
    API_CONTAINER="$("${COMPOSE[@]}" -f compose.yaml ps -q api 2>/dev/null || true)"
    if [[ -n "${API_CONTAINER}" ]] && [[ "$(docker inspect -f '{{.State.Running}}' "${API_CONTAINER}" 2>/dev/null || true)" == "true" ]]; then
      echo "API 正在运行，重新创建容器以应用新的目录挂载……"
      "${COMPOSE[@]}" -f compose.yaml up -d --no-build --force-recreate api
    fi
  fi
fi

echo "目录配置已生效。需要重新归纳数据时运行：./manage.sh scan"
echo "如果 SELinux 拒绝访问，请按 README 的 SELinux 章节设置目录标签。"

