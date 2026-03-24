#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$SCRIPT_DIR/dist"
STAMP="$(date +%Y%m%d_%H%M%S)"
PACKAGE_NAME="validador_emtp_${STAMP}.zip"
PACKAGE_PATH="$OUT_DIR/$PACKAGE_NAME"

mkdir -p "$OUT_DIR"

cd "$SCRIPT_DIR"

zip -r "$PACKAGE_PATH" \
  app.py \
  requirements.txt \
  README.md \
  QUICKSTART.md \
  src \
  .streamlit \
  -x "*/__pycache__/*" "*.DS_Store" "data/uploads/*"

open -R "$PACKAGE_PATH"
echo "Paquete creado: $PACKAGE_PATH"
