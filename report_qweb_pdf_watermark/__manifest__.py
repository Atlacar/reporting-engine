# © 2016 Therp BV <http://therp.nl>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Pdf watermark",
    "version": "20.0.1.0.0",
    "author": "Therp BV, Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "category": "Technical Settings",
    "development_status": "Production/Stable",
    "summary": "Add watermarks to your QWEB PDF reports",
    "website": "https://github.com/OCA/reporting-engine",
    # base_setup: the watermark must wrap every PDF engine, also the ones that
    # do not call super() for their own engine (Paper Muncher). Modules are
    # loaded by (depth, name) and later modules come first in the MRO, so this
    # module has to be at least as deep as base_report_paper_muncher (which
    # depends on base_setup) and sort after it by name.
    "depends": ["web", "base_setup"],
    "maintainers": ["hbrunn"],
    "data": [
        "views/ir_actions_report_xml.xml",
        "views/res_company.xml",
        "wizards/base_document_layout.xml",
    ],
    "assets": {
        "web.report_assets_pdf": [
            "/report_qweb_pdf_watermark/static/src/css/report_qweb_pdf_watermark.css"
        ],
    },
    "demo": ["demo/report.xml"],
    "installable": True,
}
