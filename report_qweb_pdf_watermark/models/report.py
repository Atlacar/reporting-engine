# © 2016 Therp BV <http://therp.nl>
# Copyright 2023 Onestein - Anjeel Haria
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from base64 import b64decode
from io import BytesIO
from logging import getLogger

from PIL import Image

from odoo import api, fields, models
from odoo.tools.binary import BinaryValue
from odoo.tools.pdf import PdfReader, PdfReadError, PdfWriter
from odoo.tools.safe_eval import safe_eval

logger = getLogger(__name__)

try:
    # we need this to be sure PIL has loaded PDF support
    from PIL import PdfImagePlugin  # noqa: F401
except ImportError:
    logger.error("ImportError: The PdfImagePlugin could not be imported")


class Report(models.Model):
    _inherit = "ir.actions.report"

    use_company_watermark = fields.Boolean(
        default=False,
        help="Use the pdf watermark defined globally in the company settings.",
    )
    pdf_watermark = fields.Binary(
        "Watermark", help="Upload an pdf file to use as an watermark on this report."
    )
    pdf_watermark_expression = fields.Char(
        "Watermark expression",
        help="An expression yielding the base64 "
        "encoded data to be used as watermark. \n"
        "You have access to variables `env` and `docs`",
    )

    def _get_watermark_company(self, docids, report_sudo):
        """Return the company to use for the company watermark.

        When printing a document in a multi-company environment, the
        watermark should match the company of the document being printed,
        not the company selected in the UI switcher.  Follows the core
        pattern of ``company_id``, then ``company_ids``, and falls back to
        ``self.env.company`` when the documents carry no company.
        """
        company = self.env["res.company"]
        if docids:
            model_name = self.model or report_sudo.model
            docs = self.env[model_name].browse(docids)
            if "company_id" in docs._fields:
                company = docs.company_id[:1]
            elif "company_ids" in docs._fields:
                company = docs.company_ids[:1]
        return company or self.env.company

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        # The watermark is merged in the streams core renders for the records,
        # before any module that depends on ``web`` (hence loaded after this
        # one) gets to append pages to them: e.g. sale_pdf_quote_builder adds
        # the quotation header, footer and product documents, which carry
        # their own look and must not be stamped. No PDF engine overrides this
        # method, so it works with every engine and whatever their load order
        # (Paper Muncher does not call ``super()`` for its own engine in
        # ``_run_pdf_engine*``). The company and the expression follow each
        # record of the stream, also when a customisation renders a batch one
        # document at a time.
        if self.env.context.get("pdf_watermark_in_streams"):
            # nested call (core renders the records one by one when it cannot
            # split a PDF): the outermost call merges the watermark
            return super()._render_qweb_pdf_prepare_streams(
                report_ref, data, res_ids=res_ids
            )
        # tell _run_pdf_engine_without_processing the watermark is merged here
        streams = super(
            Report, self.with_context(pdf_watermark_in_streams=True)
        )._render_qweb_pdf_prepare_streams(report_ref, data, res_ids=res_ids)
        if not isinstance(streams, dict):
            return streams  # html fallback when no PDF engine is set up
        report_sudo = self._get_report(report_ref)
        for res_id, stream_data in streams.items():
            stream = stream_data.get("stream")
            if not stream:
                continue
            if stream_data.get("attachment") and report_sudo.attachment_use:
                continue  # stored PDF, the watermark is already in it
            ids = [res_id] if res_id else list(res_ids or [])
            content = stream.getvalue()
            watermarked = self.with_context(res_ids=ids)._apply_pdf_watermark(
                content, report_ref
            )
            if watermarked is not content:
                stream_data["stream"] = BytesIO(watermarked)
        return streams

    @staticmethod
    def _get_watermark_content(value):
        """Return the raw bytes of a watermark value.

        Binary fields hold ``BinaryValue`` objects in 20.0. The watermark
        expression may also return base64 encoded data, as documented.
        """
        if not value:
            return None
        if isinstance(value, BinaryValue):
            return value.content
        return b64decode(value)

    @staticmethod
    def pdf_has_usable_pages(numpages):
        if numpages < 1:
            logger.error("Your watermark pdf does not contain any pages")
            return False
        if numpages > 1:
            logger.debug(
                "Your watermark pdf contains more than one page, "
                "all but the first one will be ignored"
            )
        return True

    def _apply_pdf_watermark(self, result, report_ref=False):
        """Merge the configured watermark (if any) below the pages of ``result``.

        Common to every PDF engine: it is called from whichever entry point
        the engine goes through (see ``_run_pdf_engine`` and
        ``_run_pdf_engine_without_processing``).
        """
        docids = self.env.context.get("res_ids", False)
        report_sudo = self._get_report(report_ref) if report_ref else self
        watermark = None
        if self.pdf_watermark or report_sudo.pdf_watermark:
            watermark = self._get_watermark_content(
                self.pdf_watermark or report_sudo.pdf_watermark
            )
        elif self.use_company_watermark or report_sudo.use_company_watermark:
            company = self._get_watermark_company(docids, report_sudo)
            if company.pdf_watermark:
                watermark = self._get_watermark_content(company.pdf_watermark)
        elif docids:
            watermark = safe_eval(
                self.pdf_watermark_expression
                or report_sudo.pdf_watermark_expression
                or "None",
                dict(
                    env=self.env,
                    docs=self.env[self.model or report_sudo.model].browse(docids),
                ),
            )
            watermark = self._get_watermark_content(watermark)

        if not watermark:
            return result

        pdf = PdfWriter()
        pdf_watermark = None
        try:
            pdf_watermark = PdfReader(BytesIO(watermark))
        except (UnicodeDecodeError, PdfReadError):
            # let's see if we can convert this with pillow
            try:
                Image.init()
                image = Image.open(BytesIO(watermark))
                pdf_buffer = BytesIO()
                if image.mode != "RGB":
                    image = image.convert("RGB")
                resolution = image.info.get("dpi", self.paperformat_id.dpi or 90)
                if isinstance(resolution, tuple):
                    resolution = resolution[0]
                image.save(pdf_buffer, "pdf", resolution=resolution)
                pdf_watermark = PdfReader(pdf_buffer)
            except Exception:
                logger.exception("Failed to load watermark")

        if not pdf_watermark:
            logger.error("No usable watermark found, got %s...", watermark[:100])
            return result

        if not self.pdf_has_usable_pages(len(pdf_watermark.pages)):
            return result

        for page in PdfReader(BytesIO(result)).pages:
            watermark_page = pdf.add_blank_page(
                page.mediabox.width, page.mediabox.height
            )
            watermark_page.merge_page(pdf_watermark.pages[0])
            watermark_page.merge_page(page)

        pdf_content = BytesIO()
        pdf.write(pdf_content)

        return pdf_content.getvalue()

    @api.model
    def _run_pdf_engine_without_processing(
        self,
        engine_name,
        bodies,
        report_ref=False,
        *,
        header=None,
        footer=None,
        landscape=False,
        specific_paperformat_args=None,
        **kwargs,
    ):
        result = super()._run_pdf_engine_without_processing(
            engine_name,
            bodies,
            report_ref=report_ref,
            header=header,
            footer=footer,
            landscape=landscape,
            specific_paperformat_args=specific_paperformat_args,
            **kwargs,
        )
        if self.env.context.get("pdf_watermark_in_streams"):
            # rendered through _render_qweb_pdf_prepare_streams, which merges
            # it per record
            return result
        # direct callers (account, stock reports...)
        return self._apply_pdf_watermark(result, report_ref)
