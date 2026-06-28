#!/usr/bin/env bash
# Bicep이 정상 컴파일되는지 빠르게 확인 (배포 없음)
set -e
cd "$(dirname "$0")"

az bicep build --file main.bicep --stdout >/dev/null && echo "OK: main.bicep"
az bicep build-params --file main.dev.bicepparam --stdout >/dev/null && echo "OK: main.dev.bicepparam"
