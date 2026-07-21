"""
Dual-path extraction (design hole H1).

Path A: deterministic / rule extractors (always on)
Path B: residual LLM extractor (optional, offline-safe stub by default)

Numeric / structured fields prefer Path A; free-text residual goes to Path B.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from synapse.extraction import ExtractionResult, RuleExtractor
from synapse.fhir import bundle_resources, extract_note_free_text, looks_like_fhir, parse_fhir_resource, FhirParseError
from synapse.hl7v2 import extract_nte_free_text, looks_like_hl7, parse_hl7_message, Hl7ParseError
from synapse.models import Episode, Fact, RawObject
from synapse.ontology import canonicalize_residual_predicate
from synapse.store import SemanticStore

# Free-text residue after structured keys are stripped (heuristic)
_KEY_LINE = re.compile(r"^[A-Za-z0-9_ -]+\s*[:=].+$", re.MULTILINE)


@dataclass
class DualPathResult:
    entity_name: Optional[str]
    entity_type: Optional[str]
    deterministic_facts: list[Fact] = field(default_factory=list)
    residual_facts: list[Fact] = field(default_factory=list)
    residual_text: str = ""
    path_b_used: bool = False
    path_b_backend: str = "none"

    @property
    def all_facts(self) -> list[Fact]:
        return list(self.deterministic_facts) + list(self.residual_facts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "deterministic_facts": len(self.deterministic_facts),
            "residual_facts": len(self.residual_facts),
            "residual_text": self.residual_text[:500],
            "path_b_used": self.path_b_used,
            "path_b_backend": self.path_b_backend,
            "fact_predicates": [f.predicate for f in self.all_facts],
        }


class ResidualExtractor(ABC):
    """Path B interface — LLM or heuristic residual."""

    name: str

    @abstractmethod
    def extract_residual(
        self,
        residual_text: str,
        *,
        episode: Episode,
        raw: RawObject,
        entity_id: Optional[str],
    ) -> list[Fact]:
        ...


class NoopResidualExtractor(ResidualExtractor):
    name = "noop"

    def extract_residual(self, residual_text, *, episode, raw, entity_id) -> list[Fact]:
        return []


class HeuristicResidualExtractor(ResidualExtractor):
    """
    Offline stand-in for an LLM residual path.

    Pulls simple tag-like notes: note|comment|summary|reason := value
    Only emits if entity_id is known (Path A found an entity).
    """

    name = "heuristic_residual"
    _NOTE = re.compile(
        r"(?:note|comment|summary|reason|context)\s*[:=]\s*(.+)$",
        re.IGNORECASE | re.MULTILINE,
    )

    def extract_residual(
        self,
        residual_text: str,
        *,
        episode: Episode,
        raw: RawObject,
        entity_id: Optional[str],
    ) -> list[Fact]:
        if not entity_id or not residual_text.strip():
            return []
        facts: list[Fact] = []
        for m in self._NOTE.finditer(residual_text):
            val = m.group(1).strip()
            if len(val) < 3:
                continue
            facts.append(
                Fact.create(
                    entity_id,
                    "free_text_note",
                    val[:500],
                    confidence=0.55,
                    evidence_refs=[raw.object_id, episode.episode_id],
                    source_system=raw.source_system,
                    acl_tags=list(raw.acl_tags),
                    valid_from=raw.ingested_at,
                    extractor_version="heuristic-residual/0.1",
                )
            )
        return facts


class DualPathExtractor:
    """
    Path A (RuleExtractor) then optional Path B on residual text.
    """

    def __init__(
        self,
        store: SemanticStore,
        *,
        residual: Optional[ResidualExtractor] = None,
        enable_residual: bool = True,
    ) -> None:
        self.store = store
        self.path_a = RuleExtractor(store)
        if residual is not None:
            self.residual = residual
        elif not enable_residual:
            self.residual = NoopResidualExtractor()
        else:
            # Prefer Gemini when GEMINI_API_KEY set (POC); else heuristic offline
            try:
                from synapse.llm_gemini import create_residual_extractor

                self.residual = create_residual_extractor()
            except Exception:
                self.residual = HeuristicResidualExtractor()

    def extract(self, episode: Episode, raw: RawObject) -> DualPathResult:
        primary = self.path_a.extract_from_episode(episode, raw)
        residual_text, bounded = self._compute_residual_text(episode.payload_text)
        # If structured lines consumed everything but body still has prose, keep
        # full text -- but only for the generic key:value shape. For HL7/FHIR
        # ("bounded"), an empty result from the format-aware extractor means
        # "this message truly has no free-text segment", not "the stripper
        # missed something" -- falling back to the full raw text here is
        # exactly the bug that sent every already-parsed HL7 message to the
        # residual/LLM path wholesale.
        if not bounded and not residual_text.strip() and episode.payload_text.strip():
            residual_text = episode.payload_text.strip()

        if primary is None:
            # Path B alone cannot invent entity in Phase 2 stub
            return DualPathResult(
                entity_name=None,
                entity_type=None,
                residual_text=residual_text,
                path_b_used=False,
                path_b_backend=self.residual.name,
            )

        det_facts = list(primary.facts)
        # Verify Path A structured facts (H1)
        try:
            from synapse.verifier import FactVerifier

            verifier = FactVerifier()
            for f in det_facts:
                verifier.apply(f)
                self.store.put_fact(f)
        except Exception:
            pass

        res_facts = self.residual.extract_residual(
            residual_text,
            episode=episode,
            raw=raw,
            entity_id=primary.entity.entity_id,
        )
        # Bound the residual path to a pre-defined, per-domain predicate
        # vocabulary (Claude_Instructions.md absolute constraint: no
        # freeform predicates from the LLM path). Folds known synonyms to
        # one canonical spelling first, then drops anything still outside
        # the domain's allowed set -- applied once, here, so every
        # ResidualExtractor implementation (Gemini, heuristic, future
        # backends) is bounded the same way rather than each having to
        # remember to self-police.
        bounded_facts: list[Fact] = []
        for f in res_facts:
            canonical = canonicalize_residual_predicate(f.predicate, episode.domain)
            if canonical is None:
                continue
            f.predicate = canonical
            bounded_facts.append(f)
        res_facts = bounded_facts

        try:
            from synapse.verifier import FactVerifier

            verifier = FactVerifier()
            kept: list[Fact] = []
            for f in res_facts:
                f, vr = verifier.apply(f)
                # Drop residual facts that fail hard format checks with tiny confidence
                if not vr.ok and f.confidence < 0.25:
                    continue
                self.store.put_fact(f)
                kept.append(f)
            res_facts = kept
        except Exception:
            for f in res_facts:
                self.store.put_fact(f)

        return DualPathResult(
            entity_name=primary.entity.canonical_name,
            entity_type=primary.entity.entity_type,
            deterministic_facts=det_facts,
            residual_facts=res_facts,
            residual_text=residual_text,
            path_b_used=bool(res_facts),
            path_b_backend=self.residual.name,
        )

    @staticmethod
    def _compute_residual_text(text: str) -> tuple[str, bool]:
        """
        Returns (residual_text, bounded).

        `bounded=True` means the format was positively identified (HL7v2
        or FHIR) and residual_text is the *complete* answer for that
        format's genuine free-text carrier (NTE segments / `note`
        arrays) -- an empty string is a real, final answer ("no free
        text here"), not a sign the caller should fall back to the raw
        payload. Every OBX/PID/OBR field and every FHIR resource field
        already has its own dedicated, correctly-typed extraction path;
        re-submitting the whole structured message to a residual/LLM
        pass (this proof's original behavior) both wastes a call per
        message and lets the model reinterpret values a deterministic
        parser already read precisely.

        `bounded=False` is the original generic key:value stripping,
        unchanged, for every other payload shape (CSV-drop rows, plain
        text, etc.) where the caller's existing "if still empty, keep
        the full text" fallback remains correct.
        """
        if looks_like_hl7(text):
            try:
                msg = parse_hl7_message(text)
            except Hl7ParseError:
                return "", False
            return extract_nte_free_text(msg), True
        if looks_like_fhir(text):
            try:
                data = parse_fhir_resource(text)
            except FhirParseError:
                return "", False
            resources = bundle_resources(data) if data.get("resourceType") == "Bundle" else [data]
            return extract_note_free_text(resources), True

        kept = []
        for line in text.splitlines():
            if _KEY_LINE.match(line.strip()):
                # keep free-text-ish notes keys for residual extractor
                if re.match(
                    r"^(note|comment|summary|reason|context)\s*:",
                    line.strip(),
                    re.I,
                ):
                    kept.append(line)
                continue
            if line.strip():
                kept.append(line)
        return "\n".join(kept).strip(), False
