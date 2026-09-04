from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime

class ObjetConsommableLink(SQLModel, table=True):
    objet_id: Optional[int] = Field(default=None, foreign_key="objet.id", primary_key=True)
    consommable_id: Optional[int] = Field(default=None, foreign_key="consommable.id", primary_key=True)

class UserObjetFavorisLink(SQLModel, table=True):
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", primary_key=True)
    objet_id: Optional[int] = Field(default=None, foreign_key="objet.id", primary_key=True)

class UserObjetHistoriqueLink(SQLModel, table=True):
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", primary_key=True)
    objet_id: Optional[int] = Field(default=None, foreign_key="objet.id", primary_key=True)
    date_consultation: datetime = Field(default_factory=datetime.utcnow)

class UserLieuLink(SQLModel, table=True):
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", primary_key=True)
    lieu_id: Optional[int] = Field(default=None, foreign_key="lieu.id", primary_key=True)

class Association(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nom: str
    lat: float
    long: float
    description: str

    users: List["User"] = Relationship(back_populates="association")
    objets: List["Objet"] = Relationship(back_populates="association")

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nom: str
    prenom: str
    email: str = Field(index=True, unique=True)
    password_hash: str
    is_admin: bool = Field(default=False)
    is_point_relais: bool = Field(default=False)

    # Crédits : 100 par an, 1 déduit par semaine réservée
    credits: int = Field(default=100)
    credits_reset_date: Optional[datetime] = Field(default=None)

    association_id: Optional[int] = Field(default=None, foreign_key="association.id")
    association: Optional[Association] = Relationship(back_populates="users")

    favoris: List["Objet"] = Relationship(back_populates="favoris_par", link_model=UserObjetFavorisLink)
    historique: List["Objet"] = Relationship(back_populates="consulte_par", link_model=UserObjetHistoriqueLink)
    lieux: List["Lieu"] = Relationship(back_populates="users", link_model=UserLieuLink)

class Lieu(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nom: str
    lat: float
    long: float
    adresse: str
    description: Optional[str] = Field(default=None)

    users: List["User"] = Relationship(back_populates="lieux", link_model=UserLieuLink)

class Tag(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nom: str
    objets: List["Objet"] = Relationship(back_populates="tag")

class Consommable(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nom: str
    description: Optional[str] = None
    quantite: int = 0
    prix: float
    objets: List["Objet"] = Relationship(back_populates="consommables", link_model=ObjetConsommableLink)

class Objet(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nom: str
    description: str
    image: Optional[str] = None
    disponibilite_globale: bool = Field(default=True)
    alert: bool = Field(default=False)

    current_lieu_id: Optional[int] = Field(default=None, foreign_key="lieu.id", ondelete="SET NULL")
    current_lieu: Optional[Lieu] = Relationship()

    tag_id: Optional[int] = Field(default=None, foreign_key="tag.id", ondelete="SET NULL")
    tag: Optional[Tag] = Relationship(back_populates="objets")

    association_id: Optional[int] = Field(default=None, foreign_key="association.id")
    association: Optional[Association] = Relationship(back_populates="objets")

    consommables: List[Consommable] = Relationship(back_populates="objets", link_model=ObjetConsommableLink)
    reservations: List["Reservation"] = Relationship(back_populates="objet")

    favoris_par: List[User] = Relationship(back_populates="favoris", link_model=UserObjetFavorisLink)
    consulte_par: List[User] = Relationship(back_populates="historique", link_model=UserObjetHistoriqueLink)

# Statuts de réservation (flux complet) :
# en_preparation → mis_a_disposition → retire → restitue → en_verification → terminee
# annulee : annulation avant retrait
STATUTS_BLOQUANTS = ["en_preparation", "mis_a_disposition", "retire", "restitue", "en_verification"]
STATUTS_EN_COURS = ["en_preparation", "mis_a_disposition", "retire", "restitue", "en_verification"]

STATUT_SUIVANT = {
    "en_preparation": "mis_a_disposition",
    "mis_a_disposition": "retire",
    "retire": "restitue",
    "restitue": "en_verification",
}

class Reservation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date_debut: datetime
    date_fin: datetime
    status: str = "en_preparation"
    nb_semaines: int = Field(default=1)

    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    user: Optional[User] = Relationship()

    objet_id: Optional[int] = Field(default=None, foreign_key="objet.id")
    objet: Optional[Objet] = Relationship(back_populates="reservations")

    lieu_id: Optional[int] = Field(default=None, foreign_key="lieu.id")
    lieu: Optional[Lieu] = Relationship()


class Fermeture(SQLModel, table=True):
    """Semaine de congé admin : bloque tous les objets à la réservation sur cette semaine."""
    id: Optional[int] = Field(default=None, primary_key=True)
    date_debut: datetime  # Jeudi de début de la semaine fermée
