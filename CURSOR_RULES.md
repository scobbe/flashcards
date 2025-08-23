# Cursor Terminal Rules

- Always run commands in the foreground so the user can see progress.
- Stream progress to the terminal (stdout) instead of writing run logs to files unless explicitly requested.
- Prefer zsh (`/bin/zsh -lc`) on macOS when PowerShell rendering causes issues.
- Keep outputs concise and informative, using bracketed status tags like `[step]`, `[confirm]`, `[next]`, `[done]`.
