"""Renders an HTML template to PDF bytes."""
from __future__ import annotations

from flask import render_template
from weasyprint import HTML


class PdfRenderer:
    @staticmethod
    def render(template: str, **context) -> bytes:
        return HTML(string=render_template(template, **context)).write_pdf()
