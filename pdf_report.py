"""Rapport PDF des statistiques (fpdf2, polices de base : texte en latin-1)."""
from typing import Dict, List

from fpdf import FPDF

MINT = (16, 185, 129)
DARK = (6, 95, 70)
GREY = (107, 114, 128)
ORANGE = (245, 158, 11)


def _t(text) -> str:
    """Les polices de base ne gèrent que le latin-1 : on remplace le reste."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


class _Report(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*GREY)
        self.cell(0, 8, _t(f"L'Armoire Commune - page {self.page_no()}"), align="C")


def _title(pdf: FPDF, text: str):
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 8, _t(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*MINT)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)


def _rows(pdf: FPDF, rows: List[tuple]):
    pdf.set_text_color(40, 40, 40)
    for label, value in rows:
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(125, 7, _t(label))
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, _t(value), align="R", new_x="LMARGIN", new_y="NEXT")


def _bar_chart(pdf: FPDF, title: str, labels: List[str], series: List[tuple], height: float = 42):
    """Histogramme groupé : une barre par série et par abscisse (temps)."""
    if pdf.get_y() + height + 24 > pdf.h - 20:
        pdf.add_page()
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 7, _t(title), new_x="LMARGIN", new_y="NEXT")

    x0, width = pdf.l_margin + 8, pdf.w - pdf.l_margin - pdf.r_margin - 8
    y_base = pdf.get_y() + height
    peak = max([1] + [v for _, _, values in series for v in values])

    pdf.set_draw_color(220, 220, 220)
    pdf.line(x0, y_base, x0 + width, y_base)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*GREY)
    pdf.text(pdf.l_margin, pdf.get_y() + 3, _t(str(peak)))
    pdf.text(pdf.l_margin, y_base, "0")

    n = len(labels)
    slot = width / n
    bar_w = slot * 0.8 / len(series)
    step = max(1, n // 12)  # étiquettes en abscisse espacées
    for i, label in enumerate(labels):
        for j, (_, color, values) in enumerate(series):
            h = height * values[i] / peak
            if h > 0:
                pdf.set_fill_color(*color)
                pdf.rect(x0 + i * slot + slot * 0.1 + j * bar_w, y_base - h, bar_w, h, style="F")
        if i % step == 0:
            pdf.set_text_color(*GREY)
            pdf.text(x0 + i * slot, y_base + 4, _t(label))

    # légende
    pdf.set_y(y_base + 6)
    pdf.set_font("Helvetica", "", 8)
    for name, color, _ in series:
        pdf.set_fill_color(*color)
        pdf.rect(pdf.get_x() + 1, pdf.get_y() + 1.5, 3, 3, style="F")
        pdf.set_x(pdf.get_x() + 6)
        pdf.set_text_color(40, 40, 40)
        pdf.cell(34, 6, _t(name))
    pdf.ln(8)


def build_pdf(stats: Dict) -> bytes:
    snap, act, series = stats["snapshot"], stats["activite"], stats["series"]
    pdf = _Report()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 12, _t("L'Armoire Commune - Statistiques"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*GREY)
    pdf.cell(
        0, 7,
        _t(f"Période : {stats['periode_label']} (du {stats['debut']} au {stats['fin']})"),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.cell(0, 7, _t(f"Généré le {stats['genere_le']}"), new_x="LMARGIN", new_y="NEXT")

    _title(pdf, "Activité sur la période")
    _rows(pdf, [
        ("Objets réservés (réservations)", act["reservations"]),
        ("Semaines réservées", act["semaines_reservees"]),
        ("Crédits consommés", act["credits_consommes"]),
        ("Objets rendus", act["objets_rendus"]),
        ("Annulations", f"{act['annulations']} ({act['taux_annulation']} %)"),
        ("Objets différents réservés", act["objets_distincts_reserves"]),
        ("Emprunteurs actifs", act["emprunteurs_actifs"]),
        ("Nouveaux inscrits", act["nouveaux_inscrits"]),
    ])

    _title(pdf, "État actuel")
    _rows(pdf, [
        ("Utilisateurs inscrits", snap["utilisateurs_inscrits"]),
        ("Points relais", snap["points_relais"]),
        ("Objets au catalogue", snap["objets_total"]),
        ("Objets actuellement empruntés", snap["objets_empruntes"]),
        ("Objets en vérification (révision)", snap["objets_en_verification"]),
        ("Objets en maintenance", snap["objets_en_maintenance"]),
        ("Objets en retard", snap["objets_en_retard"]),
        ("Lieux de retrait", snap["lieux"]),
        ("Réservations en cours", snap["reservations_en_cours"]),
    ])
    for s in snap["reservations_par_statut"]:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*GREY)
        pdf.cell(10)
        pdf.cell(115, 5, _t(s["label"]))
        pdf.cell(0, 5, _t(s["nombre"]), align="R", new_x="LMARGIN", new_y="NEXT")

    _title(pdf, "Évolution dans le temps")
    _bar_chart(pdf, "Réservations et retours", series["labels"], [
        ("Réservations", MINT, series["reservations"]),
        ("Retours", ORANGE, series["retours"]),
    ])

    if act["top_objets"]:
        _title(pdf, "Objets les plus réservés")
        _rows(pdf, [(o["nom"], o["reservations"]) for o in act["top_objets"]])
    if act["par_categorie"]:
        _title(pdf, "Réservations par catégorie")
        _rows(pdf, [(c["nom"], c["reservations"]) for c in act["par_categorie"]])
    if act["par_lieu"]:
        _title(pdf, "Réservations par lieu de retrait")
        _rows(pdf, [(l["nom"], l["reservations"]) for l in act["par_lieu"]])

    return bytes(pdf.output())
