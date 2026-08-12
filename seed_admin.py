"""
Script à lancer UNE SEULE FOIS (ou pour réinitialiser) afin de créer le compte
administrateur. Le mot de passe est immédiatement transformé en hash sécurisé
(werkzeug/PBKDF2) avant d'être écrit en base : il n'existe JAMAIS en clair
dans le code, la base ou le JavaScript.

Usage : python seed_admin.py
"""
import os
from datetime import datetime
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash
from database import get_db, init_db

load_dotenv()


def main():
    init_db()
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        password = input("Choisissez un mot de passe admin : ").strip()
    password_hash = generate_password_hash(password)

    db = get_db()
    existing = db.execute("SELECT id FROM admin_users WHERE username=?", (username,)).fetchone()
    if existing:
        db.execute("UPDATE admin_users SET password_hash=? WHERE username=?", (password_hash, username))
        print(f"Mot de passe mis à jour pour l'utilisateur '{username}'.")
    else:
        db.execute(
            "INSERT INTO admin_users (username, password_hash, created_at) VALUES (?,?,?)",
            (username, password_hash, datetime.utcnow().isoformat()),
        )
        print(f"Compte admin '{username}' créé avec succès.")
    db.commit()
    db.close()


if __name__ == "__main__":
    main()
