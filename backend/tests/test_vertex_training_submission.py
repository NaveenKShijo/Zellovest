"""Verify Vertex job submission without creating cloud resources."""

from unittest.mock import MagicMock

import google.cloud
from zellovest_workers.ml import vertex_training


def test_submission_creates_custom_job_and_returns_its_name(monkeypatch) -> None:
    """Submit the selected tenant and snapshot without waiting for training."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GCS_ML_BUCKET", "test-models")
    monkeypatch.setenv("VERTEX_TRAINING_IMAGE_URI", "region-docker.pkg.dev/p/r/image:tag")
    monkeypatch.setenv("GCP_SERVICE_ACCOUNT", "trainer@example.com")
    aiplatform = MagicMock()
    monkeypatch.setattr(google.cloud, "aiplatform", aiplatform, raising=False)
    job = MagicMock()
    job.resource_name = "projects/test-project/locations/us-central1/customJobs/123"
    factory = MagicMock(return_value=job)
    aiplatform.CustomJob = factory

    result = vertex_training.submit_vertex_training("tenant_001", "project.dataset.snapshot")

    assert result == job.resource_name
    job.submit.assert_called_once_with(service_account="trainer@example.com")
    spec = factory.call_args.kwargs["worker_pool_specs"][0]["container_spec"]
    assert spec["args"] == ["--feature-table", "project.dataset.snapshot", "--tenant-id", "tenant_001"]
