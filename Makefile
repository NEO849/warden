# Mnemo — reproducibility Makefile.
#
# `make install`  pip-installs the mnemo package (console_scripts entry point `mnemo`).
# `make demo`     provisions the mnemo.* structured properties on GMS (idempotent, see
#                 mnemo/provision.py), then runs the live-chain demo against that same GMS.
#                 Requires a running DataHub quickstart — see docs/REPRODUCE.md — this target
#                 does not start one.
#
# DATAHUB_GMS_URL defaults to the local quickstart; override to target any other DataHub instance.

DATAHUB_GMS_URL ?= http://localhost:8090
export DATAHUB_GMS_URL

.PHONY: install demo provision

install:
	pip install .

provision:
	mnemo provision

demo: provision
	python run_live_chain_demo.py
