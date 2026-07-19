"""
PageIndex adapter — VectifyAI pageindex client + local structure tree.

Blueprint role: Reasoning-Based Document & Structural Tree Navigator.

The PyPI `pageindex` package is a cloud API client (PageIndexClient). For
schema-on-read local POC we always keep PageIndexLite (heading/section tree).
When PAGEINDEX_API_KEY is set, cloud submit/get_tree/submit_query are available.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from synapse.pageindex import DocTree, PageIndexLite


class PageIndexAdapter:
    """Local tree navigator + optional cloud PageIndexClient."""

    def __init__(self) -> None:
        self._lite = PageIndexLite()
        self._client: Any = None
        self._package_ok = False
        self._client_ready = False
        self._error: Optional[str] = None
        self._backend = "pageindex_lite"
        self._probe()

    def _probe(self) -> None:
        try:
            from pageindex import PageIndexClient  # noqa: F401

            self._package_ok = True
            self._backend = "pageindex_package+local_tree"
        except Exception as e:  # noqa: BLE001
            self._error = f"{type(e).__name__}: {e}"
            self._backend = "pageindex_lite"
            return

        api_key = (
            os.environ.get("PAGEINDEX_API_KEY")
            or os.environ.get("PAGE_INDEX_API_KEY")
            or ""
        ).strip()
        if not api_key:
            return
        try:
            from pageindex import PageIndexClient

            self._client = PageIndexClient(api_key=api_key)
            self._client_ready = True
            self._backend = "pageindex_cloud+local_tree"
        except Exception as e:  # noqa: BLE001
            self._error = f"client:{type(e).__name__}: {str(e)[:160]}"

    @property
    def name(self) -> str:
        return self._backend

    def build(
        self,
        text: str,
        *,
        title: str = "document",
        doc_id: Optional[str] = None,
    ) -> DocTree:
        tree = self._lite.build(text, title=title, doc_id=doc_id)
        tree.backend = self._backend
        return tree

    def route(
        self,
        tree: DocTree,
        query: str,
        *,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        hits = self._lite.route(tree, query, top_k=top_k)
        for h in hits:
            h["engine_backend"] = self._backend
        return hits

    # --- Optional cloud surface (real package) ---

    def cloud_submit_document(
        self,
        file_path: str,
        *,
        mode: Optional[str] = None,
        folder_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self._client:
            return {
                "ok": False,
                "error": "PAGEINDEX_API_KEY not set or pageindex client unavailable",
                "backend": self._backend,
            }
        try:
            result = self._client.submit_document(
                file_path, mode=mode, folder_id=folder_id
            )
            return {"ok": True, "backend": self._backend, "result": result}
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "error": str(e)[:300],
                "backend": self._backend,
            }

    def cloud_get_tree(
        self, doc_id: str, *, node_summary: bool = False
    ) -> dict[str, Any]:
        if not self._client:
            return {
                "ok": False,
                "error": "PAGEINDEX_API_KEY not set or pageindex client unavailable",
                "backend": self._backend,
            }
        try:
            result = self._client.get_tree(doc_id, node_summary=node_summary)
            return {"ok": True, "backend": self._backend, "result": result}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300], "backend": self._backend}

    def cloud_submit_query(
        self, doc_id: str, query: str, *, thinking: bool = False
    ) -> dict[str, Any]:
        if not self._client:
            return {
                "ok": False,
                "error": "PAGEINDEX_API_KEY not set or pageindex client unavailable",
                "backend": self._backend,
            }
        try:
            result = self._client.submit_query(doc_id, query, thinking=thinking)
            return {"ok": True, "backend": self._backend, "result": result}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300], "backend": self._backend}

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self._backend,
            "package": "pageindex",
            "package_importable": self._package_ok,
            "cloud_client_ready": self._client_ready,
            "error": self._error,
            "role": "Reasoning-Based Document & Structural Tree Navigator",
            "note": (
                "Local DocTree always available (heading/section navigator). "
                "Cloud PageIndexClient activates when PAGEINDEX_API_KEY is in .env."
            ),
        }


def create_pageindex_adapter() -> PageIndexAdapter:
    return PageIndexAdapter()
