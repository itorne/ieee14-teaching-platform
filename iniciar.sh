#!/usr/bin/env bash
# Inicia a plataforma (Linux/macOS). Na primeira vez cria o ambiente e instala as dependencias.
set -e
cd "$(dirname "$0")"
if [ ! -x venv/bin/python ]; then
  echo "Primeira execucao: instalando a plataforma (alguns minutos, precisa de internet)."
  PY=$(command -v python3.13 || command -v python3 || true)
  if [ -z "$PY" ]; then echo "Python nao encontrado. Instale o Python 3.13."; exit 1; fi
  "$PY" -m venv venv
  venv/bin/python -m pip install --upgrade pip
  if ! venv/bin/python -m pip install -r requirements.txt; then
    echo "Falha na instalacao. Verifique a internet e execute ./iniciar.sh novamente."; rm -rf venv; exit 1
  fi
fi
echo "Abrindo a plataforma em http://localhost:8501 (Ctrl+C para encerrar)"
( sleep 6; (xdg-open http://localhost:8501 || open http://localhost:8501) >/dev/null 2>&1 || true ) &
venv/bin/python -m streamlit run app.py
