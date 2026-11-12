from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session

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


@router.get("/pdf")
def get_stats_pdf(
    periode: str = PERIODE_QUERY,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    """Rapport PDF de la période. L'app le joint ensuite à un e-mail depuis le téléphone de l'admin."""
    periode = _check(periode)
    pdf = build_pdf(compute_stats(session, periode))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="statistiques-{periode}.pdf"'},
    )
