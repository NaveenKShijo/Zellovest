"""Deprecated S3 alias — GCP-only deployments use :mod:`gcs_writer`.

Kept so historical imports (``from ...s3_writer import ...``) keep working
during the S3 → GCS migration. New code must import from
``zellovest_shared.workers.gcs_writer`` directly.
"""

from __future__ import annotations

import warnings

from zellovest_shared.workers.gcs_writer import ENTITY_FOLDERS, write_records_gz

warnings.warn(
    "zellovest_shared.workers.s3_writer is deprecated; use gcs_writer instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["ENTITY_FOLDERS", "write_records_gz"]
