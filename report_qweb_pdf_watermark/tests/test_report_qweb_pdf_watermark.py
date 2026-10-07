# © 2016 Therp BV <http://therp.nl>
# Copyright 2023 Onestein - Anjeel Haria
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import base64

from PIL import Image

from odoo import Command
from odoo.tests.common import HttpCase, tagged


# post_install: rendering web.external_layout needs the assets of all
# installed modules (e.g. website) to be loaded
@tagged("post_install", "-at_install")
class TestReportQwebPdfWatermark(HttpCase):
    def test_report_qweb_pdf_watermark(self):
        Image.init()
        # with our image, we have three
        self._test_report_images(3)

        self.env.ref("report_qweb_pdf_watermark.demo_report").write(
            {"pdf_watermark_expression": False}
        )
        # without, we have two
        self._test_report_images(2)

        self.env.ref("report_qweb_pdf_watermark.demo_report").write(
            {"pdf_watermark": self.env.user.company_id.logo}
        )
        # and now we should have three again
        self._test_report_images(3)

        # test use company watermark
        self.env.ref("report_qweb_pdf_watermark.demo_report").write(
            {"pdf_watermark": False}
        )
        self.env.ref("report_qweb_pdf_watermark.demo_report").write(
            {"use_company_watermark": True}
        )
        self.env.ref("base.main_company").write(
            {"pdf_watermark": self.env.user.company_id.logo}
        )
        self._test_report_images(3)

    def test_report_qweb_pdf_watermark_invalid(self):
        # unusable watermark data is logged and the report is left untouched
        self.env.ref("report_qweb_pdf_watermark.demo_report").write(
            {
                "pdf_watermark_expression": False,
                "pdf_watermark": base64.b64encode(b"not a pdf nor an image"),
            }
        )
        with self.assertLogs(
            "odoo.addons.report_qweb_pdf_watermark.models.report", level="ERROR"
        ) as logs:
            self._test_report_images(2)
        self.assertTrue(any("Failed to load watermark" in o for o in logs.output))
        self.assertTrue(any("No usable watermark found" in o for o in logs.output))

    def _record_stream_images(self, report, record):
        """Images of the PDF stream prepared for a single record, the way
        callers rendering one document at a time (e.g. per order) do it."""
        streams = report._render_qweb_pdf_prepare_streams(
            report.report_name, {}, res_ids=record.ids
        )
        return streams[record.id]["stream"].getvalue().count(b"/Subtype /Image")

    def _user_of_company(self, company, login):
        return self.env["res.users"].create(
            {
                "name": "Watermark " + login,
                "login": login,
                "company_id": company.id,
                "company_ids": [Command.set(company.ids)],
            }
        )

    def test_company_watermark_follows_each_rendered_record(self):
        company_a = self.env.user.company_id
        company_b = self.env["res.company"].create({"name": "Watermark Co B"})
        user_a = self.env.user
        user_b = self._user_of_company(company_b, "watermark_user_b")
        company_a.pdf_watermark = company_a.logo
        company_b.pdf_watermark = False
        demo = self.env.ref("report_qweb_pdf_watermark.demo_report")
        demo.write({"pdf_watermark_expression": False, "use_company_watermark": True})
        # the context of a batch print carries every id (as _render_qweb_pdf
        # sets it), but each record is rendered, and watermarked, on its own
        report = demo.with_context(
            res_ids=(user_a | user_b).ids, force_report_rendering=True
        )
        self.assertEqual(
            self._record_stream_images(report, user_a),
            self._record_stream_images(report, user_b) + 1,
            "company A has a watermark, company B has none",
        )
        company_b.pdf_watermark = company_a.logo
        company_a.pdf_watermark = False
        self.assertEqual(
            self._record_stream_images(report, user_b),
            self._record_stream_images(report, user_a) + 1,
            "each stream follows the company of its own record",
        )

    def test_expression_watermark_follows_each_rendered_record(self):
        user_a = self.env.user
        company_b = self.env["res.company"].create({"name": "Watermark Co B"})
        company_b.logo = False
        user_b = self._user_of_company(company_b, "watermark_user_b")
        # no ``res_ids`` in the context: a caller going through
        # _render_qweb_pdf_prepare_streams directly
        report = self.env.ref("report_qweb_pdf_watermark.demo_report").with_context(
            force_report_rendering=True
        )
        with_logo = self._record_stream_images(report, user_a)
        without_logo = self._record_stream_images(report, user_b)
        self.assertGreater(with_logo, without_logo)

    def _test_report_images(self, number):
        pdf, _ = (
            self.env["ir.actions.report"]
            .with_context(force_report_rendering=True)
            ._render_qweb_pdf(
                "report_qweb_pdf_watermark.demo_report",
                self.env["res.users"].search([]).ids,
            )
        )
        self.assertEqual(pdf.count(b"/Subtype /Image"), number)

    def test_pdf_has_usable_pages(self):
        # test 0
        numpages = 0
        # pdf_has_usable_pages(self, pdf_watermark)
        with self.assertLogs(level="ERROR"):
            self.assertFalse(
                self.env["ir.actions.report"].pdf_has_usable_pages(numpages)
            )
        # test 1
        numpages = 1
        self.assertTrue(self.env["ir.actions.report"].pdf_has_usable_pages(numpages))
        # test 2
        numpages = 2
        self.assertTrue(self.env["ir.actions.report"].pdf_has_usable_pages(numpages))
