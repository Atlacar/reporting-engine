from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPageVisibility(TransactionCase):
    def _render_minimal_layout(self, subst=True):
        report = self.env["ir.actions.report"].search([], limit=1)
        return self.env["ir.qweb"]._render(
            "web.minimal_layout",
            {"subst": subst, "body": "", "report_xml_id": report.get_external_id()[report.id]},
        )

    def test_subst_script_handles_page_visibility_classes(self):
        html = str(self._render_minimal_layout())
        for css_class in (
            "not-first-page",
            "not-last-page",
            "first-page",
            "last-page",
            "single-page",
            "multi-page",
        ):
            self.assertIn(f"'{css_class}'", html)
        # the core header/footer substitution is kept
        self.assertIn("minimal_layout_report_headers", html)
        self.assertEqual(html.count("function subst()"), 1)

    def test_no_script_when_subst_is_disabled(self):
        self.assertNotIn("function subst()", str(self._render_minimal_layout(subst=False)))
