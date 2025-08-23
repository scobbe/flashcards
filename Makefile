.PHONY: setup generate clean-venv

SHELL := /bin/zsh
VENV := .venv
PY := $(VENV)/bin/python

setup:
	python3 -m venv $(VENV)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -r requirements.txt

# Run the generators. First parse inputs, then build flashcards.
generate:
	$(PY) generate.input.py --verbose $(ARGS)
	$(PY) generate.output.py --verbose $(ARGS)

clean-venv:
	rm -rf $(VENV)
