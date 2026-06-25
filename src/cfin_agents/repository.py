from __future__ import annotations

import json
from pathlib import Path

from cfin_agents.models import FinancialDocument, MappingEntry, TargetMasterData

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "synthetic"


class SyntheticRepository:
    """Read-only repository over bundled synthetic finance data."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = data_dir
        self._documents = self._load_documents()
        self._mappings = self._load_mappings()
        self._target_master_data = self._load_target_master_data()

    def list_documents(self) -> list[FinancialDocument]:
        return sorted(self._documents.values(), key=lambda document: document.document_id)

    def get_document(self, document_id: str) -> FinancialDocument:
        try:
            return self._documents[document_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._documents))
            raise KeyError(f"Unknown document_id '{document_id}'. Available: {available}") from exc

    def find_mappings(self, mapping_type: str, source_value: str | None) -> list[MappingEntry]:
        if not source_value:
            return []
        return [
            mapping
            for mapping in self._mappings
            if mapping.mapping_type == mapping_type
            and mapping.source_value == source_value
            and mapping.status == "active"
        ]

    def target_master_data(self) -> TargetMasterData:
        return self._target_master_data.model_copy(deep=True)

    def _load_documents(self) -> dict[str, FinancialDocument]:
        raw_documents = self._read_json("documents.json")
        documents = [FinancialDocument.model_validate(item) for item in raw_documents]
        return {document.document_id: document for document in documents}

    def _load_mappings(self) -> list[MappingEntry]:
        raw_mappings = self._read_json("mappings.json")
        return [MappingEntry.model_validate(item) for item in raw_mappings]

    def _load_target_master_data(self) -> TargetMasterData:
        return TargetMasterData.model_validate(self._read_json("target_master_data.json"))

    def _read_json(self, filename: str):
        with (self.data_dir / filename).open(encoding="utf-8") as file:
            return json.load(file)
