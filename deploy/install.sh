#!/usr/bin/env bash
# 从本仓库一键部署。先构建 frontend/dist，再在对应机器运行。
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:-}" in
  pico) exec sudo bash "$task_root/deploy/install-pico.sh" ;;
  orin) exec sudo bash "$task_root/deploy/install-motion-supervisor.sh" ;;
  *) echo '用法：bash deploy/install.sh pico|orin' >&2; exit 2 ;;
esac
