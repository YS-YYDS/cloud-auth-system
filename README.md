# CloudAuthSystem

A highly reliable cloud-based authorization validation system built on FastAPI. Supports multi-product unified management, device seat binding, validity period management, license banning, and real-time cloud announcements.

## 1. Deployment (ClawCloud / Docker)
- **Recommended**: Deploy via Docker on ClawCloud App Launchpad.
- **Persistence**: You MUST mount the `/data` directory through a Volume to store `license.db`.
- **Port**: Listens on port `8000` by default.
- **Security**: You MUST set the `ADMIN_TOKEN` environment variable (Default if not set: `sk-spirit`).

## 2. Components
- **Framework**: FastAPI (Python 3.10+)
- **Database**: SQLite3 (`license.db`)
- **Server**: Uvicorn

## 3. Maintenance & CI/CD
- **GitHub Sync**: **MANDATORY**. All code and documentation changes must be pushed to the remote repository immediately after verification.
- **SQLite Vacuuming**: Recommended quarterly.

## 4. Documentation
For business logic rules and UI design guidelines, please refer to:
- `Business_Logic.md` (Chinese)
- `UI_DesignSystem.md` (English)
