"""Relatório PDF de quedas (monitorização rede) — sem dependências pesadas além de fpdf2."""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone


def _pdf_ascii(s: str, max_len: int = 120) -> str:
    t = unicodedata.normalize("NFKD", s or "").encode("ascii", "replace").decode("ascii")
    return (t[:max_len] + "…") if len(t) > max_len else t


def build_quedas_pdf_bytes(
    *,
    icmp_rows: list[dict[str, object]],
    camera_rows: list[dict[str, object]],
) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 10, _pdf_ascii(f"NeoVision - Relatorio de quedas / logs — {ts}"), ln=True)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, _pdf_ascii("Gerado pela API NeoVision. Contagem: vezes em offline (ICMP/HTTP) ou falha RTSP (camaras)."), ln=True)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, _pdf_ascii("Equipamentos ICMP"))
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 8)
    if not icmp_rows:
        pdf.cell(190, 5, _pdf_ascii("Nenhuma queda registada."))
        pdf.ln(5)
    else:
        for r in icmp_rows:
            amb = r.get("ambito", "")
            line = " | ".join(
                filter(None, [
                    str(r.get("nome", "")),
                    str(r.get("alvo", "")),
                    str(r.get("estado", "")),
                    f"quedas={r.get('quedas', 0)}",
                    f"ambito={amb}" if amb else "",
                ])
            )
            pdf.multi_cell(190, 4, _pdf_ascii(line, 130))

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(190, 6, _pdf_ascii("Camaras IP"))
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 8)
    if not camera_rows:
        pdf.cell(190, 5, _pdf_ascii("Nenhuma queda registada."))
        pdf.ln(5)
    else:
        for r in camera_rows:
            amb = r.get("ambito", "")
            parts = [
                str(r.get("nome", "")),
                str(r.get("ip", "")),
                "ativa" if r.get("ativa") else "inativa",
                f"quedas={r.get('quedas', 0)}",
            ]
            if amb:
                parts.append(f"ambito={amb}")
            line = " | ".join(parts)
            pdf.multi_cell(190, 4, _pdf_ascii(line, 130))

    return bytes(pdf.output())


def build_quedas_csv_text(
    *,
    icmp_rows: list[dict[str, object]],
    camera_rows: list[dict[str, object]],
) -> str:
    import io
    import csv

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    
    writer.writerow(["TIPO", "NOME", "ALVO/IP", "ESTADO/ATIVA", "QUEDAS", "AMBITO"])
    
    for r in icmp_rows:
        writer.writerow([
            "ICMP",
            r.get("nome", ""),
            r.get("alvo", ""),
            r.get("estado", ""),
            r.get("quedas", 0),
            r.get("ambito", "")
        ])
        
    for r in camera_rows:
        writer.writerow([
            "CAMERA",
            r.get("nome", ""),
            r.get("ip", ""),
            "ativa" if r.get("ativa") else "inativa",
            r.get("quedas", 0),
            r.get("ambito", "")
        ])
        
    return output.getvalue()
