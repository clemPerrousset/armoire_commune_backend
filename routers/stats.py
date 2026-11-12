import smtplib

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

import mailer
from auth import get_current_admin
from database import get_session
from models import User
from pdf_report import build_pdf
from stats_service import PERIODES, compute_stats

router = APIRouter(prefix="/admin/stats", tags=["Statistiques"])

PERIODE_QUERY = Query("mois", description="semaine | mois | annee")


def _check(periode: str) -> str:
    if periode not in PERIODES:
        raise HTTPException(status_code=400, detail="Période invalide (semaine, mois ou annee)")
    return periode


@router.get("")
def get_stats(
    periode: str = PERIODE_QUERY,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    return compute_stats(session, _check(periode))


@router.post("/export")
def export_stats(
    periode: str = PERIODE_QUERY,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    """Génère le rapport PDF de la période et l'envoie par e-mail à l'adresse de contact."""
    stats = compute_stats(session, _check(periode))
    pdf = build_pdf(stats)
    to = mailer.stats_recipient()
    subject = f"L'Armoire Commune - statistiques ({stats['periode_label']})"
    body = (
        "Bonjour,\n\n"
        f"Veuillez trouver ci-joint le rapport d'activité de l'Armoire Commune "
        f"({stats['periode_label']}, du {stats['debut']} au {stats['fin']}).\n\n"
        "Rapport généré automatiquement depuis l'application."
    )
    try:
        mailer.send_mail(to, subject, body, attachment=pdf, attachment_name=f"statistiques-{periode}.pdf")
    except mailer.MailNotConfigured:
        raise HTTPException(status_code=503, detail="Envoi d'e-mail non configuré sur le serveur")
    except (smtplib.SMTPException, OSError):
        raise HTTPException(status_code=502, detail="Échec de l'envoi de l'e-mail")
    return {"ok": True, "sent_to": to}
