# Delivery Pipeline — Design

**Date**: 2026-03-06
**Status**: Phase 1 implemented, Phase 2-3 pending infrastructure

## Pipeline Flow

```
PR opened
  → test-backend, test-frontend, contract-tests, typecheck (parallel)
  → migration-check (fresh PG: upgrade → verify → downgrade → re-upgrade)
  → perf-budget (bundle size threshold)
  → e2e-smoke (local API + Playwright)
  → PR review required (CODEOWNERS enforced)

Merge to main
  → deploy-staging (migrations first, then services)
  → staging-smoke (smoke_test.sh --write)
  → [MANUAL APPROVAL] deploy-production
  → production-smoke (smoke_test.sh + parity Playwright)

Failure at any stage → pipeline stops
Production health check fails → auto-rollback to previous image
```

## Phase 1 — Implemented (code changes)

| Item | File(s) | Status |
|------|---------|--------|
| CODEOWNERS | `.github/CODEOWNERS` | Created |
| CI: migration safety | `.github/workflows/ci.yml` `migration-check` job | Created |
| CI: perf budget | `.github/workflows/ci.yml` `perf-budget` job | Created |
| CI: staging deploy | `.github/workflows/ci.yml` `deploy-staging` job | Created |
| CI: manual approval gate | `deploy-production` uses `environment: production` | Created |
| CI: auto-rollback | Production deploy rolls back on healthz failure | Created |
| Post-deploy smoke | `scripts/smoke_test.sh` | Created |
| Migration check script | `scripts/check_migrations.sh` | Created |
| Rollback script | `scripts/rollback.sh` | Created |
| Pre-commit config | `.pre-commit-config.yaml` (ruff + tests) | Created |
| Staging compose | `docker-compose.staging.yml` | Created |
| Staging Caddyfile | `Caddyfile.staging` | Created |
| Ansible playbook | `infra/ansible/` | Created |

## Phase 2 — Infrastructure (requires VPS access)

### Staging setup (on VPS or second VPS)
```bash
# DNS: staging-api.lap-coach.racing → staging VPS IP (Cloudflare proxied)
# Copy repo to /opt/lap-api on staging VPS
# Create .env.staging (separate secrets, Stripe test keys)
docker compose -f docker-compose.staging.yml up -d
```

### Deploy user (on each VPS)
```bash
# Run Ansible playbook (see infra/ansible/)
ansible-playbook -i infra/ansible/inventory.ini infra/ansible/playbook.yml
```

### GitHub repository settings
```
Settings → Branches → Branch protection rules:
  Branch: main
  ✓ Require a pull request before merging
  ✓ Require approvals: 1
  ✓ Require status checks to pass:
    - test-backend
    - test-frontend
    - contract-tests
    - typecheck
    - migration-check
  ✓ Do not allow bypassing the above settings

Settings → Environments:
  staging:
    - No required reviewers (auto-deploy)
  production:
    - Required reviewers: 1
    - Deployment branches: main only

Settings → Secrets:
  STAGING_VPS_HOST: <staging-ip>
  VPS_HOST: 46.225.227.24
  VPS_USER: deploy
  VPS_SSH_KEY: <ed25519 private key>

Settings → Variables:
  STAGING_API_URL: https://staging-api.lap-coach.racing
  API_PREVIEW_URL: https://api.lap-coach.racing
```

## Phase 3 — Security hardening (requires VPS access)

### Tailscale VPN
```bash
# On VPS
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --ssh
# Restrict SSH to Tailscale only
ufw allow in on tailscale0 to any port 22
ufw deny 22
```

### Intrusion detection (fail2ban + auditd)
```bash
apt install fail2ban auditd
# See infra/ansible/playbook.yml for configuration
```

## Release Process

### Versioning
- Format: `YYYY.MM.DD-<short-sha>` (e.g., `2026.03.06-a1b2c3d`)
- Tags created automatically on production deploy
- No manual semver (overhead not justified for single-product SaaS)

### Release checklist
1. All CI checks pass on PR
2. PR reviewed and approved
3. Merge to main triggers staging deploy
4. Staging smoke test passes
5. Manual approval in GitHub Actions
6. Production deploys with auto-rollback on failure
7. Production smoke test passes

### Stop-the-line criteria
- Any smoke test failure blocks promotion
- Security scan failures block merge
- Migration downgrade failure blocks merge (non-reversible migration needs explicit approval)
- Bundle size budget exceeded blocks merge

### Rollback
```bash
# Automated: production deploy auto-rolls back on healthz failure
# Manual:
ssh deploy@<vps>
cd /opt/lap-api
./scripts/rollback.sh production
```

### Migration strategy
- **Expand/contract**: Add new columns as nullable, backfill, then add NOT NULL
- **No destructive changes**: Never DROP COLUMN in the same deploy as code changes
- **Two-phase**: Deploy code that handles both old and new schema → migrate → deploy code that requires new schema
