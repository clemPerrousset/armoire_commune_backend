from fastapi import FastAPI
from database import create_db_and_tables
from routers import users, admin_meta, objets, reservations

app = FastAPI(title="Armoire Commune API")

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

app.include_router(users.router)
app.include_router(admin_meta.router)
app.include_router(objets.router)
app.include_router(reservations.router)

@app.get("/")
def read_root():
    return {"message": "Bienvenue sur l'API de l'Armoire Commune de Dijon"}
