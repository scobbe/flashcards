.PHONY: setup generate clean-venv

SHELL := /bin/zsh
VENV := .venv
PY := $(VENV)/bin/python

setup:
	python3 -m venv $(VENV)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -r requirements.txt

# Run the generator. Does not hardcode output; pass any flags via ARGS.
# Optional: TEXT="..." to override input.txt
# Examples:
#   make generate
#   make generate TEXT="银行 人民币 得" ARGS="--verbose"
#   make generate ARGS="--outdir custom/out --verbose"
generate:
	$(PY) generate.py $(if $(TEXT),--text "$(TEXT)",) $(ARGS)

clean-venv:
	rm -rf $(VENV)
