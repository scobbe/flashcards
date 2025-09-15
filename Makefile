.PHONY: setup generate generate-debug clean-venv commit push

SHELL := /bin/zsh
VENV := .venv
PY := $(VENV)/bin/python



setup:
	python3 -m venv $(VENV)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -r requirements.txt

# Run the generators. First parse inputs, then build flashcards.
generate:
	$(PY) generate.input.py --verbose
	$(PY) generate.output.py --verbose

generate-debug:
	$(PY) generate.input.py --verbose
	$(PY) generate.output.py --verbose --debug

clean-venv:
	rm -rf $(VENV)

commit:
	git add -A
	git commit -m "feat(generator): parallel workers, shared cache, repair repair-loop; Makefile default parallel; add .cursorrules"

push:
	git push

