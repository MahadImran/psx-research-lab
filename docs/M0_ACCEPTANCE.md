# Milestone 0 (M0) Acceptance & Verification Document

**Milestone:** M0 — Foundation, Environment, $0.00 Cloud Boundary, and Tooling  
**Status:** ACCEPTED & LOCKED  
**Verification Date:** 2026-11-02  
**Sign-off Criteria:** Zero-dollar hosting contract, repository boundary separation, supply chain pinning, reproducible test runner, secret isolation.

---

## 1. M0 Scope & Objectives

Milestone 0 establishes the bedrock infrastructure and operational environment for PSX Research Lab under strict zero-dollar cost and private-first data constraints:
- Monorepo directory topology separating apps, shared schemas, and background services.
- Deterministic TypeScript (Node 24 / pnpm 10) and Python (Python 3.11 / 3.14) toolchains.
- Strict isolation between public application code (`MahadImran/psx-research-lab`) and private raw data archives (`MahadImran/psx-research-data`).
- Least-privilege CI workflow permissions and secret management.
- Complete documentation of architecture decisions, cost models, threat boundaries, and operating runbooks.

---

## 2. Requirement Verification Matrix

| Requirement | Specification Contract | Implementation Artifact | Status | Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **Zero-Dollar Budget** | Exactly $0.00 recurring cloud spend. No paid workers, paid R2, or personal hardware. | `docs/COST_LIMITS.md`, `wrangler.toml` | **VERIFIED** | Cloudflare Workers Free, D1 Free, KV Free, GitHub Actions free tier (2,000 min/mo). |
| **Repository Separation** | Public code repo, strictly private data repo. | Monorepo layout & GitHub Secrets | **VERIFIED** | Code public at `MahadImran/psx-research-lab`; raw market data isolated in private `MahadImran/psx-research-data`. |
| **Monorepo Structure** | `apps/api`, `apps/web`, `packages/shared`, `services/collector`. | `pnpm-workspace.yaml`, `pyproject.toml` | **VERIFIED** | Clean workspaces, pnpm 10.15.1, shared TypeScript package referenced across apps. |
| **Deterministic Toolchain** | Pinned dependencies with reproducible builds. | `pnpm-lock.yaml`, `services/collector/pyproject.toml` | **VERIFIED** | Python 3.11/3.14 compatible; TypeScript strict mode enabled across all TS packages. |
| **Secret Isolation** | Zero secret commits; automatic log masking. | `.gitignore`, `.github/workflows/*.yml` | **VERIFIED** | Git history audited with `git log -S`; secret tokens masked in GitHub Actions runner logs. |
| **CI/CD Pipeline** | Automated validation on every commit. | `.github/workflows/ci.yml` | **VERIFIED** | GitHub Actions Run `41385970867` (TypeScript Lint & Test: PASS, Python Collector Tests: PASS). |
| **Third-Party Licensing** | Permissive open-source licenses; proper attribution. | `services/collector/src/collector/vendor/` | **VERIFIED** | Vendored `psx_dps` MIT license verified and attributed; isolated in vendor directory. |

---

## 3. Engineering Evidence & Runner Artifacts

### 3.1 GitHub Actions CI Verification
- **Run ID:** `41385970867`
- **Workflow:** `CI` (`.github/workflows/ci.yml`)
- **Trigger:** Push to `main`
- **Runner OS:** `ubuntu-24.04` (hosted Linux runner)
- **Results:**
  - TypeScript Workspace Vitest Suite: **16 / 16 passed** (0 failures, 20s execution time)
  - Python Collector Pytest Suite: **63 / 63 passed** (0 failures, 13s execution time)
  - Exit Code: `0`

### 3.2 Secret Leakage Audit
- Scanned repository working tree and commit history:
  - No Healthchecks ping UUIDs in committed files.
  - No Cloudflare API tokens or Account IDs in tracked files.
  - No GitHub Personal Access Tokens (`ghp_...` or fine-grained tokens) in code or tests.
  - All sensitive variables loaded strictly from environment variables: `DATA_REPO_TOKEN`, `INGEST_HMAC_SECRET`, `HEALTHCHECKS_PING_URL`.

### 3.3 Documentation Completeness
The following M0 foundational architecture documents are present in `docs/`:
- `docs/ARCHITECTURE.md`: High-level system architecture and component boundaries.
- `docs/ADRS.md`: Architecture Decision Records covering zero-dollar spend, ephemeral collectors, and atomic SQLite nonces.
- `docs/COST_LIMITS.md`: Exhaustive free-tier allowance budgets and monitoring triggers.
- `docs/THREAT_MODEL.md`: Threat vectors, trust boundaries, and defensive controls.
- `docs/RUNBOOK.md`: Operational incident response and manual override procedures.

---

## 4. Milestone 0 Acceptance Sign-off

Milestone 0 meets 100% of functional, architectural, and security acceptance criteria. All automated gates pass, and zero cost assumptions have been validated.
