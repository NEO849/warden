#!/usr/bin/env bash
# Warden infra-spike setup. 4-space indents (zsh/bash safe).
# Stands up a local DataHub quickstart + sample data. Requires Docker running.
set -euo pipefail

echo "==> [1/4] Python venv + DataHub CLI"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r ../requirements.txt

echo "==> [2/4] DataHub quickstart (Docker; first run pulls images, ~minutes)"
datahub docker quickstart

echo "==> [3/4] Ingest sample metadata (gives us lineage/assets to reason over)"
datahub docker ingest-sample-data

echo "==> [4/4] Done."
echo "    UI:  http://localhost:9002   (login datahub / datahub)"
echo "    GMS: http://localhost:8080"
echo "    Next: create an access token in the UI, fill .env, then:"
echo "      datahub properties upsert -f warden_memory_property.yaml"
echo "      python 01_write_read_memory.py"
