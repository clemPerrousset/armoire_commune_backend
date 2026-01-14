from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime

# Link Table for Many-to-Many between Objet and Consommable
class ObjetConsommableLink(SQLModel, table=True):
    objet_id: Optional[int] = Field(default=None, foreign_key="objet.id", primary_key=True)
    consommable_id: Optional[int] = Field(default=None, foreign_key="consommable.id", primary_key=True)

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nom: str
    prenom: str
    email: str = Field(index=True, unique=True)
    password_hash: str
    is_admin: bool = Field(default=False)

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

    tag_id: Optional[int] = Field(default=None, foreign_key="tag.id")
    tag: Optional[Tag] = Relationship(back_populates="objets")

    consommables: List[Consommable] = Relationship(back_populates="objets", link_model=ObjetConsommableLink)
    reservations: List["Reservation"] = Relationship(back_populates="objet")

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
