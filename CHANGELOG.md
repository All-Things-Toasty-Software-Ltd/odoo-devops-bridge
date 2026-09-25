# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/).

Where applicable, this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.2.0] - 26-09-2026

### Added
- **Views**: Added all primary Odoo views and layout structure.
- **Wizard**: Introduced syncing wizard for DevOps providers.
- **Services**: Service handling logic for GitHub (primary focus), GitLab, and YouTrack integration.
- **Models**: Data models and base Odoo model inheritance logic.
- **Controllers**: Webhook controllers and HTTP routing.
- **Data & Security**: Automated cron jobs, sequence data for simple backup automation, and access security rules.
- **Tests**: Test suites covering core DevOps Bridge functionality.
- **Docs**: Base `index.rst` documentation structure and introductory administration guide.

### Changed
- Updated manifest (`__manifest__.py`) and module initialization (`__init__.py`) files to enforce correct load order and module details.
- Updated root project configuration files to match repository standards.

### Fixed
- Fixed layout view issues and typos in comment handling routines.

---

## [0.1.0] - 21-09-2026

### Added
- Initialized project repository using the standard Odoo App Template scaffolding.