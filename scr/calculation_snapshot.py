"""Снимок проверяемого расчёта для последующего ручного экспорта."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    from data_assembly import AssembledData
    from pressure_chart import PressureChartData
    from result_export import DataSheetValues


@dataclass(frozen=True)
class CalculationSnapshot:
    data: AssembledData | DataSheetValues
    sections: list[tuple[str, pd.DataFrame | None]]
    pressure_chart: PressureChartData
    report_data: dict[str, Any]
    input_files: tuple[Path, ...]
    filename_stem: str

    def validate_destination(self, path: Path, suffix: str) -> None:
        if path.suffix.lower() != suffix:
            raise ValueError(f"Сохраните результат в формате {suffix}.")
        if path.resolve() in {source.resolve() for source in self.input_files}:
            raise ValueError("Результат нельзя сохранять поверх входной книги или выгрузки.")
