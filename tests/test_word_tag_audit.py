"""Tag inventory resolves real Jinja aliases without marking whole loops as used."""
import unittest

from jinja2 import Environment
from audit_word_tags import References, fields


class WordTagAuditTest(unittest.TestCase):
    def test_loop_index_aliases_and_assignments_resolve_to_the_same_field(self):
        visitor = References()
        visitor.visit(Environment().parse(
            '{% for item in periods %}{% set v=item.boundary.start.vlo_pa %}'
            '{{ v }}{% endfor %}{{ periods[-1].boundary.end.vlo_pa }}'
            '{{ periods.p1.boundary.start.vlo_pa }}'))
        self.assertIn('period.boundary.start.vlo_pa', visitor.paths)
        self.assertIn('period.boundary.end.vlo_pa', visitor.paths)
        self.assertNotIn('v', visitor.paths)

    def test_iterating_periods_does_not_mark_all_period_fields_as_used(self):
        available = fields({'periods': [{'number': 1, 'date_start': '', 'date_end': ''}],
                            'current_date': ''})
        visitor = References()
        visitor.visit(Environment().parse('{% for p in periods %}{{ p.number }}{% endfor %}'))
        self.assertEqual(available & visitor.paths, {'period.number'})
        self.assertEqual(available-visitor.paths, {'period.date_start','period.date_end','current_date'})

    def test_conditions_and_dictionary_access_are_counted_as_usage(self):
        visitor = References()
        visitor.visit(Environment().parse(
            "{% if periods[0]['deltas']['show_no_degradation_text'] %}"
            "{{ source['data_start_date'] }}{% endif %}"))
        self.assertIn('period.deltas.show_no_degradation_text', visitor.paths)
        self.assertIn('source.data_start_date', visitor.paths)


if __name__ == '__main__':
    unittest.main()
