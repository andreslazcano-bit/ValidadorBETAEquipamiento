#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CANDIDATE_DIRS=(
  "$SCRIPT_DIR"
  "$SCRIPT_DIR/beta_revision_emtp"
  "$HOME/002. Proyecto Revisión Equipamiento 2026/beta_revision_emtp"
)

if [[ -n "${VALIDADOR_EMTP_DIR:-}" ]]; then
  CANDIDATE_DIRS=("$VALIDADOR_EMTP_DIR" "${CANDIDATE_DIRS[@]}")
fi

PROJECT_DIR=""
for d in "${CANDIDATE_DIRS[@]}"; do
  if [[ -f "$d/app.py" && -f "$d/requirements.txt" ]]; then
    PROJECT_DIR="$d"
    break
  fi
done

if [[ -z "$PROJECT_DIR" ]]; then
  osascript -e 'display alert "No se encontró la carpeta del proyecto" message "Debes tener una carpeta beta_revision_emtp con app.py y requirements.txt.\n\nSugerencia: crea un alias del archivo dentro del proyecto, no una copia en Desktop." as critical'
  exit 1
fi

WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
VENV_DIR="$WORKSPACE_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"

if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display alert "No se encontró Python 3" message "Instala Python 3 en este Mac para ejecutar el validador." as critical'
  exit 1
fi

if [[ ! -x "$VENV_PY" ]]; then
  echo "Configurando entorno por primera vez..."
  python3 -m venv "$VENV_DIR"
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PY" -m pip install -r "$PROJECT_DIR/requirements.txt"
fi

cd "$PROJECT_DIR"
"$VENV_PY" -m streamlit run app.py --server.headless true --server.address 127.0.0.1 --browser.serverAddress 127.0.0.1 --server.port 8501 &
STREAMLIT_PID=$!

# Espera a que el servidor local quede listo y abre navegador automáticamente.
for _ in {1..80}; do
  if nc -z 127.0.0.1 8501 >/dev/null 2>&1; then
    open "http://127.0.0.1:8501"
    break
  fi
  sleep 0.25
done

wait "$STREAMLIT_PID"
