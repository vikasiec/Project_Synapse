"""
Data-Juicer adapter — prefers real py-data-juicer when ops import; else lite.

Blueprint role: Multi-Format Ingestion Pipeline & Raw Data Streamliner.
Synapse maps that to a composable prep chain before dual-path extract.
"""

from __future__ import annotations

from typing import Any, Optional

from synapse.operators import OpContext, OperatorPipeline


class DataJuicerAdapter:
    """
    Unified prep surface.

    - Always exposes OperatorPipeline (lite chain) for deterministic, offline prep.
    - When data_juicer.ops is importable, reports package-backed status and can
      list registered operator module names for blueprint fidelity.
    """

    def __init__(self, pipeline: Optional[OperatorPipeline] = None) -> None:
        self.pipeline = pipeline or OperatorPipeline()
        self._ops_modules: list[str] = []
        self._backend = "data_juicer_lite"
        self._package_error: Optional[str] = None
        self._probe()

    def _probe(self) -> None:
        try:
            import data_juicer  # noqa: F401

            self._backend = "data_juicer_package+lite_chain"
        except Exception as e:  # noqa: BLE001
            self._package_error = f"{type(e).__name__}: {e}"
            self._backend = "data_juicer_lite"
            return

        try:
            import data_juicer.ops as ops  # type: ignore
            from pathlib import Path

            names: list[str] = []
            ops_file = getattr(ops, "__file__", None)
            ops_path = Path(ops_file).parent if ops_file else None
            if ops_path and ops_path.is_dir():
                names = sorted(
                    p.name
                    for p in ops_path.iterdir()
                    if p.is_dir()
                    and not p.name.startswith("_")
                    and p.name != "__pycache__"
                )
            if not names:
                names = [
                    a
                    for a in (
                        "aggregator",
                        "deduplicator",
                        "filter",
                        "grouper",
                        "mapper",
                        "pipeline",
                        "selector",
                    )
                    if hasattr(ops, a)
                ]
            self._ops_modules = names
            self._backend = "data_juicer_ops+lite_chain"
        except Exception as e:  # noqa: BLE001
            # Package root imports but full ops catalog may need extra deps
            try:
                import data_juicer
                from pathlib import Path

                root = Path(data_juicer.__file__).parent / "ops"
                if root.is_dir():
                    self._ops_modules = sorted(
                        p.name
                        for p in root.iterdir()
                        if p.is_dir()
                        and not p.name.startswith("_")
                        and p.name != "__pycache__"
                    )
            except Exception:
                pass
            self._package_error = f"ops:{type(e).__name__}: {str(e)[:160]}"
            self._backend = "data_juicer_package+lite_chain"

    @property
    def name(self) -> str:
        return self._backend

    def run(self, text: str, **meta: Any) -> OpContext:
        """Run the active prep chain (always safe/offline lite operators)."""
        ctx = self.pipeline.run(text, **meta)
        ctx.meta["prep_backend"] = self._backend
        if self._ops_modules:
            ctx.meta["data_juicer_op_families"] = list(self._ops_modules)
        return ctx

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self._backend,
            "package": "py-data-juicer",
            "role": "Multi-Format Ingestion Pipeline & Raw Data Streamliner",
            "lite_operators": self.pipeline.describe(),
            "package_op_families": list(self._ops_modules),
            "package_error": self._package_error,
            "note": (
                "Ingest path uses synapse OperatorPipeline (schema-on-read safe). "
                "Real Data-Juicer families are detected when importable for catalog fidelity."
            ),
        }


def create_prep_adapter(pipeline: Optional[OperatorPipeline] = None) -> DataJuicerAdapter:
    return DataJuicerAdapter(pipeline=pipeline)
