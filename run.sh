#!/bin/bash
# RotaHub - sobe o backend (e frontend, que o backend ja serve junto)
# Uso: ./run.sh   (rode a partir da pasta raiz do projeto, onde fica "backend/")

set -e  # para o script se qualquer comando falhar, em vez de continuar quebrado

cd "$(dirname "$0")/backend"

if [ ! -d "venv" ]; then
    echo "Criando ambiente virtual (primeira vez)..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Instalando/atualizando dependencias..."
pip install -q -r requirements.txt

echo ""
echo "Subindo o RotaHub em http://localhost:8000"
echo "(Ctrl+C para parar)"
echo ""
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
