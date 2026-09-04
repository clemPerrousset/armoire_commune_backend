from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from database import create_db_and_tables
from routers import users, admin_meta, objets, reservations, fermetures
import os

# Créer le dossier images avant le montage StaticFiles
# (StaticFiles vérifie l'existence du dossier à l'initialisation, pas au startup)
os.makedirs("/data/images", exist_ok=True)

app = FastAPI(title="Armoire Commune API")

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

# Serve uploaded object images
app.mount("/images", StaticFiles(directory="/data/images"), name="images")

app.include_router(users.router)
app.include_router(admin_meta.router)
app.include_router(objets.router)
app.include_router(reservations.router)
app.include_router(fermetures.router)

@app.get("/")
def read_root():
    return {"message": "Bienvenue sur l'API de l'Armoire Commune de Dijon"}
