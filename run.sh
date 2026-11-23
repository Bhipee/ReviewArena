#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ "${REVIEWARENA_BACKEND:-local}" = local ]; then
    export REVIEWARENA_API_URL=http://127.0.0.1:8766/v1
    export REVIEWARENA_MODEL=default_model
    export REVIEWARENA_API_KEY=local
fi
exec .venv/bin/python -m streamlit run app.py --server.headless true --browser.gatherUsageStats false --server.address 127.0.0.1 "$@"
