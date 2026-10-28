# Collaboration

- Use a feature branch for each Issue and a PR to merge into `main`.
- PRs must document what changed, affected data rights, validation steps and evidence.
- Tests must run: `python -m pytest -q`; CI also runs `ruff check .`.
- Do not add real race data or data-provider adapters without documented rights approval.
- Model claims must identify BACKTEST/SHADOW/actual status and cohort.
- Do not include paywall/payment/voting automation in MVP.
- Define ownership, revenue split and confidentiality with collaborators before granting access.