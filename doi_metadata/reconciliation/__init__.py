"""Reconciliation — detect conflicts across sources."""

from doi_metadata.reconciliation.discrepancy_report import build_discrepancy_report
from doi_metadata.reconciliation.engine import reconcile

__all__ = ["reconcile", "build_discrepancy_report"]
