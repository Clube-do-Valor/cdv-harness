---
paths:
  - "{app_dir}/config/**/*.php"
  - "{app_dir}/.env.example"
  - "{app_dir}/.env.*.template"
---

# Configuration and environment variables

- Any new environment variable read through `config()`/`env()` MUST be added to every environment template the repository keeps (`env_templates` in `.claude/harness/profile.yaml`, usually `.env.example` and a production template) in the same change that introduces it.
- `.env.example` uses empty placeholders (`MY_TOKEN=`); a template that CI fills uses `$VAR` references (`MY_TOKEN=$MY_TOKEN`) for sensitive values and plain values only for non-sensitive data.
- Never commit real secrets to any template — placeholders and `$VAR` references only.
- A variable that exists only in a local `.env` is invisible to production provisioning: it will be absent at deploy time and the feature will fail silently. The templates are the contract for what every environment must provide.
- `env()` is read only inside `config/*.php`; application code reads `config()`. Prefer giving config keys a safe default in `config/*.php` when one exists; the template entry is still required so the variable is discoverable.
