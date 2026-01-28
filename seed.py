from sqlmodel import Session, select
from database import engine, create_db_and_tables
from models import User, Tag, Lieu, Consommable, Objet, Association
from auth import get_password_hash

def seed():
    create_db_and_tables()
    with Session(engine) as session:
        # Check if already seeded
        if session.exec(select(User).where(User.email == "admin@armoire.com")).first():
            print("Already seeded.")
            return

        # Association
        asso = Association(
            nom="La Bricole",
            lat=47.3220,
            long=5.0415,
            description="Association de bricolage du centre-ville"
        )
        session.add(asso)
        session.commit()
        session.refresh(asso)

        # Users
        admin = User(
            nom="Admin",
            prenom="Super",
            email="admin@armoire.com",
            password_hash=get_password_hash("admin123"),
            is_admin=True,
            association_id=asso.id
        )
        user1 = User(
            nom="Dupont",
            prenom="Jean",
            email="jean@test.com",
            password_hash=get_password_hash("password"),
            is_admin=False,
            association_id=asso.id
        )
        session.add(admin)
        session.add(user1)

        # Tags
        tags = ["Bricolage", "Jardinage", "Cuisine", "Maison", "Loisirs", "Événementiel"]
        tag_objs = []
        for t_name in tags:
            tag = Tag(nom=t_name)
            session.add(tag)
            tag_objs.append(tag)

        # Lieu
        lieu = Lieu(nom="La Ressourcerie", lat=47.3220, long=5.0415, adresse="Dijon")
        session.add(lieu)

        # Consommable
        vis = Consommable(nom="Vis", prix=0.10, quantite=100)
        clous = Consommable(nom="Clous", prix=0.05, quantite=200)
        session.add(vis)
        session.add(clous)

        session.commit()

        # Refresh to get IDs
        for t in tag_objs:
            session.refresh(t)
        session.refresh(vis)

        # Objets
        # We need to make sure tag_objs[0] has an ID.
        perceuse = Objet(
            nom="Perceuse Percussion",
            description="Une perceuse puissante.",
            quantite=2,
            tag_id=tag_objs[0].id, # Bricolage
            disponibilite_globale=True,
            association_id=asso.id
        )
        session.add(perceuse)

        # Append consumable
        perceuse.consommables.append(vis)

        session.commit()
        print("Seeding complete.")

if __name__ == "__main__":
    seed()
