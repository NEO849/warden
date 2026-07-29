# Warden — reproducibility Makefile.
#
# `make install`  pip-installs the warden package (console_scripts entry point `warden`).
# `make demo`     provisions the warden.* structured properties on GMS (idempotent, see
#                 warden/provision.py), then runs the live-chain demo against that same GMS.
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
	warden provision

demo: provision
	python run_live_chain_demo.py
