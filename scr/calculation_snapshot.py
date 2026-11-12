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
    from station_profiles import StationTariffs


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
    tariffs_station_id: str = ''
    station_tariffs: StationTariffs | None = None
    vna_section_slots: tuple = ()

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
        by_algorithm = dict(self.pressure_chart.compressor_pair_ranks_by_algorithm or {})
        by_algorithm[self.pressure_chart.compressor_algorithm] = choices
        return replace(self, pressure_chart=replace(self.pressure_chart, compressor_pair_ranks=choices,
                       compressor_pair_ranks_by_algorithm=by_algorithm),
                       report_data=context)

    def with_compressor_algorithm(self, algorithm: int, tables=None) -> CalculationSnapshot:
        """Switch only TOP-10 tables, compressor charts and selected-pair Word fields."""
        from compressor_degradation_chart import selected_compressor_pairs
        from reporting import _vna_top_context
        import pandas as pd

        if isinstance(algorithm, bool) or not isinstance(algorithm, Integral) or algorithm not in (1, 2):
            raise ValueError('Номер алгоритма должен быть 1 или 2.')
        chart = self.pressure_chart
        if chart is None:
            raise ValueError('Нет данных ТОП-10 ВНА.')
        available = dict(chart.vna_top10_algorithms or {chart.compressor_algorithm: chart.vna_top10})
        if tables is not None:
            available[algorithm] = tables
        if algorithm not in available:
            raise ValueError('Алгоритм 2 ещё не рассчитан.')
        if algorithm == chart.compressor_algorithm and tables is None:
            return self
        remembered = dict(chart.compressor_pair_ranks_by_algorithm or {})
        remembered[chart.compressor_algorithm] = dict(chart.compressor_pair_ranks or {})
        choices = dict(remembered.get(algorithm, {}))
        active = available[algorithm] or []
        selected = selected_compressor_pairs(active, choices)
        context = copy.deepcopy(self.report_data)
        context['compressor_algorithm'] = int(algorithm)
        for period in context.get('periods', []):
            row = selected.get(period.get('number'))
            period['vna_top1'] = _vna_top_context([row] if row is not None else None)
        slots = self.vna_section_slots
        if not slots:
            slots = tuple((index, title, int(table.attrs['period_number']))
                for index, (title, table) in enumerate(self.sections)
                if table is not None and 'period_number' in table.attrs and
                {'rank', 'vna_interval'} <= set(table.columns))
        by_period = {int(table.attrs['period_number']): table for table in active
                     if table is not None and 'period_number' in table.attrs}
        sections = list(self.sections)
        for index, title, number in slots:
            table = by_period.get(number)
            if table is None or table.empty:
                reason = table.attrs.get('empty_reason') if table is not None else None
                table = pd.DataFrame({'Сообщение': [reason or 'Нет подходящих пар.']})
            else:
                table = table.drop(columns=['share_percent'], errors='ignore')
            sections[index] = (title + (' · Алгоритм 2' if algorithm == 2 else ''), table)
        return replace(self, sections=sections, report_data=context, vna_section_slots=slots,
            pressure_chart=replace(chart, vna_top10=active, compressor_algorithm=int(algorithm),
                compressor_pair_ranks=choices, vna_top10_algorithms=available,
                compressor_pair_ranks_by_algorithm=remembered))

    def validate_destination(self, path: Path, suffix: str) -> None:
        if path.suffix.lower() != suffix:
            raise ValueError(f"Сохраните результат в формате {suffix}.")
        if path.resolve() in {source.resolve() for source in self.input_files}:
            raise ValueError("Результат нельзя сохранять поверх входной книги или выгрузки.")
