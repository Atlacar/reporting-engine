# © 2016 Therp BV <http://therp.nl>
# Copyright 2023 Onestein - Anjeel Haria
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import base64
from io import BytesIO
from unittest import mock

from PIL import Image

from odoo import Command
from odoo.tests.common import HttpCase, TransactionCase, tagged
from odoo.tools.pdf import PdfReader


class TestReportQwebPdfWatermark(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Create test report template programmatically
        cls.env["ir.ui.view"].create(
            {
                "name": "Test Watermark Report Template",
                "type": "qweb",
                "key": "report_qweb_pdf_watermark.test_report_view",
                "arch": """
                <t t-name="report_qweb_pdf_watermark.test_report_view">
                    <t t-call="web.html_container">
                        <t t-call="web.external_layout">
                            <div class="page">
                                <ul>
                                    <li t-foreach="docs" t-as="doc">
                                        <t t-out="doc.name" />
                                    </li>
                                </ul>
                            </div>
                        </t>
                    </t>
                </t>
            """,
            }
        )

        # Create test report action
        cls.test_report = cls.env["ir.actions.report"].create(
            {
                "name": "Test Watermark Report",
                "model": "res.users",
                "report_type": "qweb-pdf",
                "report_name": "report_qweb_pdf_watermark.test_report_view",
                "pdf_watermark_expression": "docs[:1].company_id.logo",
            }
        )

        logo1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        logo2 = "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

        # Ensure company has a logo for testing
        if not cls.env.user.company_id.logo:
            # Create a minimal test logo (1x1 transparent PNG)
            cls.env.user.company_id.logo = logo1 + logo2

    def test_report_qweb_pdf_watermark(self):
        Image.init()
        # with our image, we have three
        self._test_report_images(3)

        self.test_report.write({"pdf_watermark_expression": False})
        # without, we have two
        self._test_report_images(2)

        self.test_report.write({"pdf_watermark": self.env.user.company_id.logo})
        # and now we should have three again
        self._test_report_images(3)

        # test use company watermark
        self.test_report.write({"pdf_watermark": False})
        self.test_report.write({"use_company_watermark": True})
        self.env.user.company_id.write({"pdf_watermark": self.env.user.company_id.logo})
        self._test_report_images(3)

    def test_watermark_merged_once_by_wkhtmltopdf(self):
        """Rendered through ``_render_qweb_pdf_prepare_streams`` and the engine's
        ``_run_pdf_engine_without_processing``: merged by the former only."""
        Report = self.registry["ir.actions.report"]
        original = Report._apply_pdf_watermark
        with mock.patch.object(
            Report, "_apply_pdf_watermark", autospec=True, side_effect=original
        ) as apply:
            pdf, _ = (
                self.env["ir.actions.report"]
                .with_context(force_report_rendering=True)
                ._render_qweb_pdf(self.test_report.report_name, self.env.user.ids)
            )
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(pdf.count(b"/Subtype /Image"), 3)

    def test_direct_engine_call_merged_once(self):
        """account/stock reports call the engine without the streams preparation."""
        Report = self.registry["ir.actions.report"]
        original = Report._apply_pdf_watermark
        report = self.test_report.with_context(force_report_rendering=True)
        report.pdf_watermark = self.env.user.company_id.logo
        with mock.patch.object(
            Report, "_apply_pdf_watermark", autospec=True, side_effect=original
        ) as apply:
            pdf = report._run_pdf_engine_without_processing(
                "wkhtmltopdf", ["<html><body><p>direct</p></body></html>"]
            )
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(pdf.count(b"/Subtype /Image"), 1)

    def _test_report_images(self, number):
        pdf, _ = (
            self.env["ir.actions.report"]
            .with_context(force_report_rendering=True)
            ._render_qweb_pdf(
                self.test_report.report_name,
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


# post_install, so that auto-installed modules such as iap are available
@tagged("post_install", "-at_install")
class TestReportQwebPdfWatermarkCompany(TransactionCase):
    def _create_report(self, model):
        return self.env["ir.actions.report"].create(
            {
                "name": f"Test Watermark Report {model}",
                "model": model,
                "report_type": "qweb-pdf",
                "report_name": "report_qweb_pdf_watermark.test_report_view",
            }
        )

    def test_get_watermark_company(self):
        other_company = self.env["res.company"].create({"name": "Watermark Co"})
        self.assertNotEqual(self.env.company, other_company)
        report = self._create_report("res.partner")
        partner = self.env["res.partner"].create(
            {"name": "Partner", "company_id": other_company.id}
        )
        shared_partner = self.env["res.partner"].create({"name": "Shared"})

        # no documents: company from the environment
        self.assertEqual(report._get_watermark_company([], report), self.env.company)
        # document company_id wins over the environment company
        self.assertEqual(
            report._get_watermark_company(partner.ids, report), other_company
        )
        # the first document carrying a company is used
        self.assertEqual(
            report._get_watermark_company((shared_partner | partner).ids, report),
            other_company,
        )
        # document without a company: company from the environment
        self.assertEqual(
            report._get_watermark_company(shared_partner.ids, report),
            self.env.company,
        )

    def test_get_watermark_company_ids(self):
        # iap.account only has company_ids; iap is auto-installed with web
        if "iap.account" not in self.env:
            self.skipTest("iap is not installed")
        other_company = self.env["res.company"].create({"name": "Watermark Co"})
        report = self._create_report("iap.account")
        service = self.env["iap.service"].create(
            {
                "name": "Watermark",
                "technical_name": "report_qweb_pdf_watermark_test",
                "description": "Watermark test service",
                "unit_name": "Credits",
                "integer_balance": True,
            }
        )
        account = self.env["iap.account"].create(
            {
                "service_id": service.id,
                "company_ids": [Command.set(other_company.ids)],
            }
        )
        self.assertEqual(
            report._get_watermark_company(account.ids, report), other_company
        )


def _make_pdf(pages=1, color="red"):
    """A PDF whose pages each hold one image (counted through /Subtype /Image)."""
    first = Image.new("RGB", (60, 60), color)
    buffer = BytesIO()
    first.save(
        buffer,
        "pdf",
        save_all=True,
        append_images=[Image.new("RGB", (60, 60), color) for _ in range(pages - 1)],
    )
    return buffer.getvalue()


# post_install, so that auto-installed modules such as iap are available
@tagged("post_install", "-at_install")
class TestReportQwebPdfWatermarkEngines(TransactionCase):
    """The watermark is merged whatever the PDF engine, once, per company."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.watermark = base64.b64encode(_make_pdf(1, "blue")).decode()
        cls.plain_pdf = _make_pdf(2)
        cls.report = cls.env["ir.actions.report"].create(
            {
                "name": "Test Watermark Engine Report",
                "model": "res.partner",
                "report_type": "qweb-pdf",
                "report_name": "web.report_layout",
                "pdf_watermark": cls.watermark,
            }
        )

    def _images(self, pdf):
        return pdf.count(b"/Subtype /Image")

    def test_apply_keeps_every_page(self):
        result = self.report._apply_pdf_watermark(self.plain_pdf, self.report.report_name)
        self.assertEqual(len(PdfReader(BytesIO(result)).pages), 2)
        self.assertGreater(self._images(result), self._images(self.plain_pdf))

    def test_apply_without_watermark_is_identity(self):
        self.report.pdf_watermark = False
        result = self.report._apply_pdf_watermark(self.plain_pdf, self.report.report_name)
        self.assertEqual(result, self.plain_pdf)

    def test_apply_image_watermark(self):
        buffer = BytesIO()
        Image.new("RGBA", (20, 20), (0, 255, 0, 128)).save(buffer, "PNG")
        self.report.pdf_watermark = base64.b64encode(buffer.getvalue()).decode()
        result = self.report._apply_pdf_watermark(self.plain_pdf, self.report.report_name)
        self.assertEqual(len(PdfReader(BytesIO(result)).pages), 2)
        self.assertGreater(self._images(result), self._images(self.plain_pdf))

    def test_company_watermark_follows_document_company(self):
        other_company = self.env["res.company"].create(
            {"name": "Watermark Co", "pdf_watermark": self.watermark}
        )
        self.env.company.pdf_watermark = False
        report = self.report
        report.write({"pdf_watermark": False, "use_company_watermark": True})
        partner = self.env["res.partner"].create(
            {"name": "Partner", "company_id": other_company.id}
        )
        shared = self.env["res.partner"].create({"name": "Shared"})
        in_other = report.with_context(res_ids=partner.ids)._apply_pdf_watermark(
            self.plain_pdf, report.report_name
        )
        self.assertGreater(self._images(in_other), self._images(self.plain_pdf))
        # no company on the document: the (watermark-less) env company
        no_watermark = report.with_context(res_ids=shared.ids)._apply_pdf_watermark(
            self.plain_pdf, report.report_name
        )
        self.assertEqual(no_watermark, self.plain_pdf)

    def test_document_layout_wizard_sets_company_watermark(self):
        wizard = self.env["base.document.layout"].create({})
        self.assertEqual(wizard.company_id, self.env.company)
        wizard.pdf_watermark = self.watermark
        self.assertEqual(
            self.env.company.pdf_watermark.content, wizard.pdf_watermark.content
        )
        self.assertTrue(self.env.company.pdf_watermark)
        arch = self.env["base.document.layout"].get_view(
            self.env.ref("web.view_base_document_layout").id
        )["arch"]
        self.assertIn('name="pdf_watermark"', arch)

    def test_paper_muncher_engine(self):
        """An engine skipping ``_run_pdf_engine_without_processing`` (Paper
        Muncher): watermark merged, once, whatever the module load order."""
        if not self.env["ir.module.module"].search_count(
            [("name", "=", "base_report_paper_muncher"), ("state", "=", "installed")]
        ):
            self.skipTest("base_report_paper_muncher is not installed")
        self.env["ir.ui.view"].create(
            {
                "name": "Test Watermark Muncher Template",
                "type": "qweb",
                "key": "report_qweb_pdf_watermark.test_muncher_view",
                "arch": """
                <t t-name="report_qweb_pdf_watermark.test_muncher_view">
                    <t t-call="web.html_container">
                        <main><div class="article" t-foreach="docs" t-as="doc"
                            t-att-data-oe-model="doc._name" t-att-data-oe-id="doc.id">
                            <t t-out="doc.name"/></div></main>
                    </t>
                </t>""",
            }
        )
        report = self.report.copy(
            {
                "report_type": "qweb-pdf-paper-muncher",
                "report_name": "report_qweb_pdf_watermark.test_muncher_view",
                "model": "res.users",
            }
        )
        one_page = _make_pdf(1)
        Report = self.registry["ir.actions.report"]
        original = Report._apply_pdf_watermark
        with mock.patch.object(
            Report, "_run_paper_muncher", return_value=one_page
        ) as muncher, mock.patch.object(
            Report, "get_pdf_engine_state", return_value="ok"
        ), mock.patch.object(
            Report, "_apply_pdf_watermark", autospec=True, side_effect=original
        ) as apply:
            pdf, _ = report.with_context(force_report_rendering=True)._render_qweb_pdf(
                report.report_name, self.env.user.ids
            )
        muncher.assert_called_once()
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(len(PdfReader(BytesIO(pdf)).pages), 1)
        self.assertGreater(self._images(pdf), self._images(one_page))
