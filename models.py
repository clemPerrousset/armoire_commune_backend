from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime

# Link Table for Many-to-Many between Objet and Consommable
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

    association_id: Optional[int] = Field(default=None, foreign_key="association.id")
    association: Optional[Association] = Relationship(back_populates="users")

    favoris: List["Objet"] = Relationship(back_populates="favoris_par", link_model=UserObjetFavorisLink)
    historique: List["Objet"] = Relationship(back_populates="consulte_par", link_model=UserObjetHistoriqueLink)

class Lieu(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nom: str
    lat: float
    long: float
    adresse: str

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
    quantite: int = 1
    disponibilite_globale: bool = Field(default=True)  # Status (e.g. Broken/Working)
    alert: bool = Field(default=False)  # True if object was not returned on time and is reserved by someone else

    tag_id: Optional[int] = Field(default=None, foreign_key="tag.id", ondelete="SET NULL")
    tag: Optional[Tag] = Relationship(back_populates="objets")

    association_id: Optional[int] = Field(default=None, foreign_key="association.id")
    association: Optional[Association] = Relationship(back_populates="objets")

    consommables: List[Consommable] = Relationship(back_populates="objets", link_model=ObjetConsommableLink)
    reservations: List["Reservation"] = Relationship(back_populates="objet")

    favoris_par: List[User] = Relationship(back_populates="favoris", link_model=UserObjetFavorisLink)
    consulte_par: List[User] = Relationship(back_populates="historique", link_model=UserObjetHistoriqueLink)

class Reservation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date_debut: datetime
    date_fin: datetime
    status: str = "active"  # active, terminee, annulee

    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    user: Optional[User] = Relationship()

    objet_id: Optional[int] = Field(default=None, foreign_key="objet.id")
    objet: Optional[Objet] = Relationship(back_populates="reservations")

    lieu_id: Optional[int] = Field(default=None, foreign_key="lieu.id")
    lieu: Optional[Lieu] = Relationship()
