#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${AI_DEVOPS_HOME:-$HOME/ai-devops}"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
API_BIN="${REPO_ROOT}/orchestrator/bin/zoe_tool_api.py"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

COMMAND="${1:-}"

# pgrep heuristic: matches processes launched with 'orchestrator/bin/<name>' in argv.
# May miss processes started from inside the directory (e.g. 'python zoe-daemon.py').
daemon_running() {
  pgrep -f 'orchestrator/bin/zoe-daemon.py' >/dev/null 2>&1
}

monitor_running() {
  pgrep -f 'orchestrator/bin/monitor.py' >/dev/null 2>&1
}

_require_api_bin() {
  if [[ ! -f "${API_BIN}" ]]; then
    echo "zoe tool api not found: ${API_BIN}" >&2
    exit 1
  fi
}

case "${COMMAND}" in
  schema)
    _require_api_bin
    exec "${PYTHON_BIN}" "${API_BIN}" schema --pretty
    ;;
  doctor)
    echo "ai_devops_home=$REPO_ROOT"
    echo "python_bin=$PYTHON_BIN"
    echo "api_bin=$API_BIN"
    if [[ -f "${API_BIN}" ]]; then
      echo "api_bin_ok=yes"
    else
      echo "api_bin_ok=missing"
    fi
    if daemon_running; then
      echo "zoe_daemon=running"
    else
      echo "zoe_daemon=missing"
    fi
    if monitor_running; then
      echo "monitor=running"
    else
      echo "monitor=missing"
    fi
    ;;
  call)
    _require_api_bin
    TOOL_NAME="${2:-}"
    if [[ -z "${TOOL_NAME}" ]]; then
      echo "usage: invoke_zoe_tool.sh call <tool-name> '<json-args>'" >&2
      exit 1
    fi
    TOOL_ARGS='{}'
    if [[ "${3:-}" == "--args-file" ]]; then
      ARGS_FILE="${4:-}"
      if [[ -z "${ARGS_FILE}" || ! -f "${ARGS_FILE}" ]]; then
        echo "usage: invoke_zoe_tool.sh call <tool-name> --args-file <path>" >&2
        exit 1
      fi
      TOOL_ARGS="$(cat "${ARGS_FILE}")"
    elif [[ -n "${3:-}" ]]; then
      TOOL_ARGS="${3}"
    fi
    REQUEST_FILE="$(mktemp)"
    trap 'rm -f "${REQUEST_FILE}"' EXIT
    printf '{"tool":"%s","args":%s}\n' "${TOOL_NAME}" "${TOOL_ARGS}" > "${REQUEST_FILE}"
    "${PYTHON_BIN}" "${API_BIN}" invoke --request-file "${REQUEST_FILE}"
    STATUS=$?
    rm -f "${REQUEST_FILE}"
    trap - EXIT
    exit "${STATUS}"
    ;;
  *)
    echo "usage:" >&2
    echo "  invoke_zoe_tool.sh schema" >&2
    echo "  invoke_zoe_tool.sh doctor" >&2
    echo "  invoke_zoe_tool.sh call <tool-name> '<json-args>'" >&2
    exit 1
    ;;
esac
