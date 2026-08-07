"""One-time migrations for earlier companion installations."""

from honeyos.migration.legacy import (
    MigrationError,
    MigrationResult,
    migrate_legacy_home,
)

__all__ = ["MigrationError", "MigrationResult", "migrate_legacy_home"]

