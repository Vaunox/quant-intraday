"""Errors for the research training pipeline (P2A.6)."""


class PipelineError(RuntimeError):
    """A training-pipeline step failed (empty/degenerate dataset, bad pooling input)."""
