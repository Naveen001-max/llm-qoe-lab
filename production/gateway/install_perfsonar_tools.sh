#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 2; }
echo "Installs perfSONAR tools bundle from the official installer."
echo "Use only on a dedicated measurement node; verify OS compatibility first."
read -r -p "Type INSTALL-PERFSONAR to continue: " c
[[ "$c" == "INSTALL-PERFSONAR" ]] || exit 1
curl -fsSL https://downloads.perfsonar.net/install | sh -s - tools
