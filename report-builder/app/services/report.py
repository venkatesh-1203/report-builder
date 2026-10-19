"""Step 7: build the PDF report."""
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK, ACCENT, MUTED = colors.HexColor("#16202A"), colors.HexColor("#234E9D"), colors.HexColor("#5B6773")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], alignment=0, textColor=INK, fontSize=22, spaceAfter=4),
        "sub": ParagraphStyle("s", parent=base["Normal"], textColor=MUTED, fontSize=10, spaceAfter=14),
        "h": ParagraphStyle("h", parent=base["Heading2"], textColor=INK, fontSize=13, spaceBefore=14, spaceAfter=6),
        "body": ParagraphStyle("b", parent=base["Normal"], textColor=INK, fontSize=10.5, leading=15),
        "small": ParagraphStyle("sm", parent=base["Normal"], textColor=MUTED, fontSize=9, leading=12),
    }


def _fit_image(path: Path, width: float) -> Image:
    w, h = ImageReader(str(path)).getSize()
    return Image(str(path), width=width, height=width * h / w)


def build_pdf(out_path: Path, *, title: str, analysis: dict, summary: str, charts_dir: Path,
              chart_names: list[str], quality: dict, issues: list, warnings: list) -> Path:
    st = _styles()
    t, p = analysis["totals"], analysis["period"]
    currency = analysis["currency"]
    story = [
        Paragraph(escape(title), st["title"]),
        Paragraph(f"Period: {p['start']} to {p['end']} ({p['days']} days)", st["sub"]),
    ]

    kpis = [
        ("Revenue", f"{currency} {t['revenue']:,.0f}"),
        ("Orders", f"{t['orders']:,}"),
        ("Avg. order value", f"{currency} {t['avg_order_value']:,.0f}" if t["avg_order_value"] is not None else "-"),
        ("Units sold", f"{t['units']:,.0f}" if t["units"] is not None else "-"),
    ]
    table = Table([[v for _, v in kpis], [k for k, _ in kpis]], colWidths=[4.3 * cm] * 4)
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, 0), 16), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT), ("TEXTCOLOR", (0, 1), (-1, 1), MUTED),
        ("FONTSIZE", (0, 1), (-1, 1), 9), ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("LINEABOVE", (0, 0), (-1, 0), 1.2, ACCENT), ("TOPPADDING", (0, 0), (-1, 0), 8),
    ]))
    story += [table, Paragraph("Summary", st["h"]), Paragraph(escape(summary), st["body"])]

    additional_metrics = [
        f"Average daily revenue: {currency} {t['avg_daily_revenue']:,.0f}",
        f"Active sales days: {analysis['active_days']:,}/{p['days']:,}",
        f"Products: {analysis['product_count']:,}",
    ]
    if t["avg_units_per_order"] is not None:
        additional_metrics.append(f"Average units per order: {t['avg_units_per_order']:,.2f}")
    story.append(Paragraph(" &nbsp;|&nbsp; ".join(additional_metrics), st["small"]))

    wow = analysis.get("week_over_week")
    if wow and wow.get("change_pct") is not None:
        story.append(Paragraph(
            f"Last 7 days: {currency} {wow['last_7_days']:,.0f} vs previous 7 days: "
            f"{currency} {wow['previous_7_days']:,.0f} "
            f"({wow['change_pct']:+}%)", st["small"]))

    story.append(Paragraph("Charts", st["h"]))
    for name in chart_names:
        story += [_fit_image(charts_dir / f"{name}.png", 16.5 * cm), Spacer(1, 8)]

    story.append(Paragraph("Data quality", st["h"]))
    story.append(Paragraph(
        f"Rows read: {quality['rows_read']:,} &nbsp;|&nbsp; Rows used: {quality['rows_valid']:,} "
        f"&nbsp;|&nbsp; Bad rows skipped: {quality['rows_rejected']:,} "
        f"&nbsp;|&nbsp; Duplicates removed: {quality.get('duplicates_removed', 0):,}", st["body"]))
    for w in warnings:
        story.append(Paragraph("&bull; " + escape(w), st["small"]))
    if issues:
        rows = [["Row", "Problem"]] + [[str(i["row"]), Paragraph(escape(i["problem"]), st["small"])] for i in issues[:10]]
        issue_table = Table(rows, colWidths=[2 * cm, 14 * cm])
        issue_table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9DEE4")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story += [Spacer(1, 6), issue_table]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(2 * cm, 1.2 * cm, "Automated Report Builder")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
        canvas.restoreState()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=2 * cm, bottomMargin=2 * cm, title=title).build(
        story, onFirstPage=footer, onLaterPages=footer)
    return out_path
