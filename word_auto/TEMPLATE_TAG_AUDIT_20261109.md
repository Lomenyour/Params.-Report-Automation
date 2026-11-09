# Теги Word — проверка 09.11.2026

Проверена текущая пользовательская копия `word_auto/templates/template_mapped.docx`.
DOCX не изменялся. `period.*` объединяет обращения в цикле, через `periods[0]`,
`periods[-1]` и `periods.p1`. Наличие в условии также считается использованием.
Это статический аудит: условный текст может не выводиться в конкретном отчёте.
`source.selection_mode` и `source.selected_intervals[0].*` доступны только в ручном режиме.

Доступно полей: 102; используются: 50; не используются: 52; неизвестных ссылок: 0.

## Не используются

- `{{ economics.vna_nominal_threshold_percent }}`
- `{{ period.boundary.delta.fgo_fto_pa }}`
- `{{ period.boundary.delta.fgo_pa }}`
- `{{ period.boundary.delta.fto_pa }}`
- `{{ period.boundary.delta.vlo_pa }}`
- `{{ period.boundary.end.b_priv }}`
- `{{ period.boundary.end.date }}`
- `{{ period.boundary.end.fgo_pa }}`
- `{{ period.boundary.end.fto_pa }}`
- `{{ period.boundary.end.n_priv_mw }}`
- `{{ period.boundary.start.b_priv }}`
- `{{ period.boundary.start.date }}`
- `{{ period.boundary.start.date_short }}`
- `{{ period.boundary.start.fgo_pa }}`
- `{{ period.boundary.start.fto_pa }}`
- `{{ period.boundary.start.n_priv_mw }}`
- `{{ period.date_end }}`
- `{{ period.date_start }}`
- `{{ period.deltas.eta_gtu_percent }}`
- `{{ period.deltas.eta_gtu_pp }}`
- `{{ period.in_period }}`
- `{{ period.number }}`
- `{{ period.ordinal_prepositional }}`
- `{{ period.vna_top1.count }}`
- `{{ period.vna_top1.delta_days }}`
- `{{ period.vna_top1.delta_eta_pp }}`
- `{{ period.vna_top1.delta_p_mbar }}`
- `{{ period.vna_top1.delta_t_c }}`
- `{{ period.vna_top1.interval }}`
- `{{ period.vna_top1.point_1.date }}`
- `{{ period.vna_top1.point_1.eta_percent }}`
- `{{ period.vna_top1.point_1.pi_k }}`
- `{{ period.vna_top1.point_1.t_kk_c }}`
- `{{ period.vna_top1.point_2.date }}`
- `{{ period.vna_top1.point_2.eta_percent }}`
- `{{ period.vna_top1.point_2.pi_k }}`
- `{{ period.vna_top1.point_2.t_kk_c }}`
- `{{ period.vna_top1.rank }}`
- `{{ period.vna_top1.share_percent }}`
- `{{ schema_version }}`
- `{{ source.file_name }}`
- `{{ source.generated_at }}`
- `{{ source.invalid_date_rows }}`
- `{{ source.selected_intervals[0].end }}`
- `{{ source.selected_intervals[0].start }}`
- `{{ source.selection_mode }}`
- `{{ summary.calculated_total_hours }}`
- `{{ summary.nominal_power_records }}`
- `{{ summary.nominal_vna_records }}`
- `{{ turbine.number }}`
- `{{ weighted_deltas.eta_gtu_percent }}`
- `{{ weighted_deltas.eta_gtu_pp }}`

## Используются

- `{{ current_date }}`
- `{{ economics.annualized.fuel_overrun_nm3 }}`
- `{{ economics.annualized.fuel_overrun_rub }}`
- `{{ economics.annualized.total_cost_rub }}`
- `{{ economics.annualized.underproduction_mwh }}`
- `{{ economics.annualized.underproduction_rub }}`
- `{{ economics.power_threshold_mw }}`
- `{{ economics.total.fuel_overrun_nm3 }}`
- `{{ economics.total.fuel_overrun_rub }}`
- `{{ economics.total.total_cost_rub }}`
- `{{ economics.total.underproduction_mwh }}`
- `{{ economics.total.underproduction_rub }}`
- `{{ economics.vna_threshold_percent }}`
- `{{ period.boundary.end.date_short }}`
- `{{ period.boundary.end.fgo_fto_pa }}`
- `{{ period.boundary.end.power_n_mw }}`
- `{{ period.boundary.end.vlo_pa }}`
- `{{ period.boundary.end.vna_percent }}`
- `{{ period.boundary.start.fgo_fto_pa }}`
- `{{ period.boundary.start.power_n_mw }}`
- `{{ period.boundary.start.vlo_pa }}`
- `{{ period.boundary.start.vna_percent }}`
- `{{ period.degradation_period }}`
- `{{ period.deltas.b_priv }}`
- `{{ period.deltas.b_priv_percent }}`
- `{{ period.deltas.n_priv }}`
- `{{ period.deltas.n_priv_percent }}`
- `{{ period.deltas.show_no_degradation_text }}`
- `{{ period.ordinal_genitive }}`
- `{{ period.vna_top1.point_1.p_nk_mbar }}`
- `{{ period.vna_top1.point_1.t_nk_c }}`
- `{{ period.vna_top1.point_1.vna_percent }}`
- `{{ period.vna_top1.point_2.p_nk_mbar }}`
- `{{ period.vna_top1.point_2.t_nk_c }}`
- `{{ period.vna_top1.point_2.vna_percent }}`
- `{{ period_count }}`
- `{{ source.data_end_date }}`
- `{{ source.data_start_date }}`
- `{{ summary.nominal_power_hours }}`
- `{{ summary.nominal_vna_hours }}`
- `{{ summary.total_operating_hours }}`
- `{{ tariffs.electricity_cost_rub_per_mwh }}`
- `{{ tariffs.electricity_rub_per_mwh }}`
- `{{ tariffs.gas_rub_per_1000_nm3 }}`
- `{{ turbine.model }}`
- `{{ turbine.name }}`
- `{{ weighted_deltas.b_priv }}`
- `{{ weighted_deltas.b_priv_percent }}`
- `{{ weighted_deltas.n_priv }}`
- `{{ weighted_deltas.n_priv_percent }}`
