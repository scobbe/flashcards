

<!-- Source: .ruler/context/00-shared-context.md -->

## Shared general context (authoritative source)

General, cross-project agent knowledge lives in the **`scobbe/context`** repo,
vendored here as the **`shared-context/`** git submodule. Treat it as an
**authoritative source** of general rules and context, read alongside this repo's
own rules: see `shared-context/CLAUDE.md` (generated) or browse
`shared-context/.ruler/rules/` and `shared-context/.ruler/context/`.

General knowledge is **not duplicated here** — it lives in `shared-context/`; this
repo holds only what is specific to it. Refresh with
`git submodule update --remote shared-context`.

When adding or changing any rule / context / workflow, always ask:
**"Should this belong in the general Context repo?"** If it's general (not
specific to this repo), put it in `scobbe/context`, not here.



<!-- Source: .ruler/rules/00-overview.md -->

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
