#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${AI_DEVOPS_HOME:-$HOME/ai-devops}"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
API_BIN="${REPO_ROOT}/orchestrator/bin/zoe_tool_api.py"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

if [[ ! -f "${API_BIN}" ]]; then
  echo "zoe tool api not found: ${API_BIN}" >&2
  exit 1
fi

COMMAND="${1:-}"

case "${COMMAND}" in
  schema)
    exec "${PYTHON_BIN}" "${API_BIN}" schema --pretty
    ;;
  call)
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
    echo "  invoke_zoe_tool.sh call <tool-name> '<json-args>'" >&2
    exit 1
    ;;
esac
