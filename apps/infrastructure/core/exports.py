"""PDF and Excel export helpers for FlockIQ batch reports."""
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor('#3d5a99')
STRIPE = colors.HexColor('#f4f7fe')
GRID = colors.HexColor('#e2e8f0')


def generate_batch_report(batch) -> bytes:
    """Return a PDF byte string for a single batch summary."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f'Batch Report: {batch.batch_name}', styles['Title']))
    story.append(
        Paragraph(
            f'Farm: {batch.farm.name} | Generated: {date.today()}',
            styles['Normal'],
        )
    )
    story.append(Spacer(1, 0.5 * cm))

    data = [
        ['Field', 'Value'],
        ['Bird Type', batch.get_bird_type_display()],
        ['Placement Date', str(batch.placement_date)],
        ['Initial Count', str(batch.initial_count)],
        ['Current Count', str(batch.current_count)],
        ['Cycle Day', str(batch.cycle_day)],
        ['Mortality Rate', f'{batch.mortality_rate_pct:.1f}%'],
        ['Status', batch.get_status_display()],
    ]

    t = Table(data, colWidths=[6 * cm, 10 * cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, STRIPE]),
        ('GRID', (0, 0), (-1, -1), 0.5, GRID),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t)

    doc.build(story)
    return buffer.getvalue()


def generate_batch_excel(batch) -> bytes:
    """Return an Excel (.xlsx) byte string for a single batch summary."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Batch Summary'

    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill('solid', fgColor='3D5A99')

    for col, header in enumerate(['Field', 'Value'], 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill

    rows = [
        ('Batch Name', batch.batch_name),
        ('Bird Type', batch.get_bird_type_display()),
        ('Placement Date', str(batch.placement_date)),
        ('Initial Count', batch.initial_count),
        ('Current Count', batch.current_count),
        ('Cycle Day', batch.cycle_day),
        ('Mortality Rate', f'{batch.mortality_rate_pct:.1f}%'),
        ('Status', batch.get_status_display()),
    ]
    for row_idx, (field, value) in enumerate(rows, 2):
        ws.cell(row=row_idx, column=1, value=field)
        ws.cell(row=row_idx, column=2, value=value)

    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 30

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
