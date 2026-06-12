from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image as ReportLabImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import Project, Shot


def export_storyboard_pdf(project: Project, output_path: Path, layout: str = "two_per_page") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.45 * inch,
        rightMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
    )

    styles = getSampleStyleSheet()
    story = []

    if layout == "thumbnails":
        for start in range(0, len(project.shots), 6):
            story.append(_thumbnail_page(project, project.shots[start : start + 6], styles))
            story.append(Spacer(1, 0.1 * inch))
    else:
        for index, shot in enumerate(project.shots):
            story.append(_shot_block(project, shot, styles, compact=(layout != "one_per_page")))
            if layout == "two_per_page" and index % 2 == 0:
                story.append(Spacer(1, 0.18 * inch))
            elif layout == "one_per_page":
                story.append(Spacer(1, 0.5 * inch))

    if not story:
        story.append(Paragraph("No shots in storyboard.", styles["Normal"]))

    doc.build(story)


def _shot_block(project: Project, shot: Shot, styles, compact: bool = True) -> KeepTogether:
    image_cell = _image_flowable(project, shot)
    details = [
        Paragraph(f"<b>{_escape(shot.shot_id)}</b>", styles["Heading4"]),
        Paragraph(f"<b>Status:</b> {_escape(shot.status)}", styles["Normal"]),
        Paragraph(f"<b>Title:</b> {_escape(shot.title)}", styles["Normal"]),
        Paragraph(f"<b>Scene:</b> {_escape(shot.scene)}", styles["Normal"]),
        Paragraph(f"<b>Sequence:</b> {_escape(shot.sequence)}", styles["Normal"]),
        Paragraph(f"<b>Description:</b> {_escape(shot.description)}", styles["Normal"]),
        Paragraph(f"<b>Action:</b> {_escape(shot.action_note)}", styles["Normal"]),
        Paragraph(f"<b>Camera:</b> {_escape(shot.camera_note)}", styles["Normal"]),
        Paragraph(f"<b>Character:</b> {_escape(shot.character_note)}", styles["Normal"]),
        Paragraph(f"<b>Dialogue:</b> {_escape(shot.dialogue)}", styles["Normal"]),
        Paragraph(f"<b>Lighting:</b> {_escape(shot.lighting_note)}", styles["Normal"]),
        Paragraph(f"<b>Transition:</b> {_escape(shot.transition_note)}", styles["Normal"]),
        Paragraph(f"<b>3D Camera:</b> {_escape(_camera_summary(shot))}", styles["Normal"]),
        Paragraph(f"<b>Duration:</b> {shot.duration_seconds:.1f}s", styles["Normal"]),
        Paragraph(f"<b>Tags:</b> {_escape(', '.join(shot.tags))}", styles["Normal"]),
    ]

    row_height = 4.75 * inch if compact else 9.0 * inch
    table = Table(
        [[image_cell, details]],
        colWidths=[3.3 * inch, 4.0 * inch],
        rowHeights=[row_height],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return KeepTogether(table)


def _thumbnail_page(project: Project, shots: list[Shot], styles) -> Table:
    cells = []
    for shot in shots:
        cells.append(
            [
                _image_flowable(project, shot, max_width=2.1 * inch, max_height=1.25 * inch),
                Paragraph(f"<b>{_escape(shot.shot_id)}</b><br/>{_escape(shot.title)}<br/>{shot.duration_seconds:.1f}s", styles["Normal"]),
            ]
        )
    while len(cells) < 6:
        cells.append(["", ""])
    rows = [[cells[i], cells[i + 1]] for i in range(0, 6, 2)]
    table = Table(rows, colWidths=[3.75 * inch, 3.75 * inch], rowHeights=[2.1 * inch] * 3)
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _image_flowable(project: Project, shot: Shot, max_width=3.05 * inch, max_height=4.25 * inch):
    image_rel_path = shot.preview_image_path or shot.image_path
    image_path = project.root_path / image_rel_path if image_rel_path else None
    if image_path and image_path.exists():
        image = ReportLabImage(str(image_path))
        image._restrictSize(max_width, max_height)
        return image

    placeholder = Table([["No Image"]], colWidths=[max_width], rowHeights=[max_height])
    placeholder.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, colors.grey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.grey),
            ]
        )
    )
    return placeholder


def _escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _camera_summary(shot: Shot) -> str:
    if not shot.camera_data:
        return ""
    parts = []
    for key in ("angle", "focal_length", "location", "rotation"):
        value = shot.camera_data.get(key)
        if value:
            parts.append(f"{key}: {value}")
    return "; ".join(parts)
