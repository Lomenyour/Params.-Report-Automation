"""Снимок проверяемого расчёта для последующего ручного экспорта."""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from pathlib import Path
from numbers import Integral
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
    correction_sheet: Any = None
    gas_passport: Any = None
    correction_profile: Any = None
    book_profile: Any = None

    def with_compressor_pair(self, period: int, rank: int) -> CalculationSnapshot:
        """A new export snapshot; analytical tables and TOP-10 stay untouched."""
        from compressor_degradation_chart import selected_compressor_pairs
        from reporting import _vna_top_context

        if any(isinstance(value, bool) or not isinstance(value, Integral) or value < 1
               for value in (period, rank)):
            raise ValueError("Период и номер пары должны быть положительными целыми числами.")
        if self.pressure_chart is None:
            raise ValueError("Нет результатов расчёта компрессора.")
        choices = dict(self.pressure_chart.compressor_pair_ranks or {})
        choices[period] = rank
        selected = selected_compressor_pairs(self.pressure_chart.vna_top10, choices)
        current = selected_compressor_pairs(self.pressure_chart.vna_top10,
                                             self.pressure_chart.compressor_pair_ranks)
        if rank == int(current[period].get("rank", 1)):
            return self
        context = copy.deepcopy(self.report_data)
        for item in context.get("periods", []):
            if item.get("number") == period:
                # Keep the existing Word field name for template compatibility.
                item["vna_top1"] = _vna_top_context([selected[period]])
        return replace(self, pressure_chart=replace(self.pressure_chart, compressor_pair_ranks=choices),
                       report_data=context)

    def validate_destination(self, path: Path, suffix: str) -> None:
        if path.suffix.lower() != suffix:
            raise ValueError(f"Сохраните результат в формате {suffix}.")
        if path.resolve() in {source.resolve() for source in self.input_files}:
            raise ValueError("Результат нельзя сохранять поверх входной книги или выгрузки.")
