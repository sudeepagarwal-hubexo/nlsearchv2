"""Pytest defaults — avoid blocking Databricks CLI auth during unit tests."""

from __future__ import annotations

import os

os.environ.setdefault("NLSEARCH_SKIP_DATABRICKS_CLI", "true")
