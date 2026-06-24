# flashcards — agent rules

Chinese flashcard generator (Python). See README for the pipeline.

## Project rules

- **Command execution:** use Make targets for standard workflows only
  (`make setup`, `make generate`, `make generate-debug`). One-off
  maintenance/debug tasks should be standalone scripts checked in under
  `scripts/` and run directly. For ad-hoc ops (cache rebuilds, mass edits),
  prefer `scripts/*.py` or `scripts/*.sh` over adding new Make targets.
- **Shell assumptions:** zsh on macOS. Prefer absolute paths when passing file
  or directory arguments.
