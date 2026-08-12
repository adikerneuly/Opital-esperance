"""
Base de données réelle (SQLite), totalement séparée du code du site.
Fichier généré : hopital.db (à la racine du projet, hors du HTML).
"""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("DATABASE_PATH", "hopital.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name_fr TEXT NOT NULL,
            name_en TEXT NOT NULL,
            name_ht TEXT NOT NULL,
            description_fr TEXT NOT NULL,
            description_en TEXT NOT NULL,
            description_ht TEXT NOT NULL,
            icon TEXT DEFAULT 'stethoscope',
            image_path TEXT,
            duration_minutes INTEGER DEFAULT 30,
            price_htg INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            service_id INTEGER,
            appointment_date TEXT NOT NULL,
            appointment_time TEXT NOT NULL,
            message TEXT,
            status TEXT DEFAULT 'en_attente',
            created_at TEXT NOT NULL,
            FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS contact_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            subject TEXT,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()

    # Valeurs par défaut des paramètres modifiables (uniquement si absentes)
    default_settings = {
        "phone": "+509 3456 7890",
        "address": "12 Rue Capois, Port-au-Prince, Haïti",
        "doctor_name": "",
        "appointment_hours": "Lun - Sam : 7h00 - 19h00 | Urgences 24/7",
        "logo_image": "",
        "hero_image": "",
    }
    for key, value in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

    cur.execute("SELECT COUNT(*) AS c FROM services")
    if cur.fetchone()["c"] == 0:
        now = datetime.utcnow().isoformat()
        demo_services = [
            ("Médecine générale", "General Medicine", "Medsin jeneral",
             "Consultation médicale générale pour le diagnostic et le suivi de vos problèmes de santé courants.",
             "General medical consultation for the diagnosis and follow-up of common health issues.",
             "Konsiltasyon medikal jeneral pou dyagnostik ak swiv pwoblèm sante kouran ou yo.",
             "stethoscope", None, 30, 1500),
            ("Pédiatrie", "Pediatrics", "Pedyatri",
             "Suivi médical complet des nourrissons, enfants et adolescents, de la naissance à 18 ans.",
             "Complete medical follow-up for infants, children and teenagers, from birth to age 18.",
             "Swiv medikal konplè pou tibebe, timoun ak adolesan, depi nesans jiska 18 an.",
             "baby", None, 30, 1500),
            ("Gynécologie-Obstétrique", "Gynecology & Obstetrics", "Jinekoloji-Obstetrik",
             "Soins de santé de la femme, suivi de grossesse, accouchement et planification familiale.",
             "Women's health care, pregnancy follow-up, delivery and family planning.",
             "Swen sante fanm, swiv gwosès, akouchman ak planifikasyon familyal.",
             "heart-pulse", None, 45, 2000),
            ("Cardiologie", "Cardiology", "Kadyoloji",
             "Diagnostic et traitement des maladies du cœur et du système cardiovasculaire.",
             "Diagnosis and treatment of heart and cardiovascular system diseases.",
             "Dyagnostik ak tretman maladi kè ak sistèm kadyovaskilè.",
             "activity", None, 45, 2500),
            ("Dentisterie", "Dentistry", "Dantis",
             "Soins dentaires complets : détartrage, extractions, soins des caries et prothèses.",
             "Complete dental care: scaling, extractions, cavity treatment and prosthetics.",
             "Swen dantè konplè: detatraj, ekstraksyon, swen kari ak pwotèz.",
             "smile", None, 30, 1200),
            ("Laboratoire & Imagerie", "Laboratory & Imaging", "Laboratwa ak Imajri",
             "Analyses de sang et d'urine, échographies et radiographies réalisées sur place.",
             "Blood and urine tests, ultrasounds and X-rays performed on site.",
             "Analiz san ak pipi, echografi ak radyografi ki fèt sou plas.",
             "flask-conical", None, 20, 1000),
        ]
        for s in demo_services:
            cur.execute("""
                INSERT INTO services (name_fr, name_en, name_ht, description_fr, description_en,
                    description_ht, icon, image_path, duration_minutes, price_htg, is_active,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (*s, now, now))
        conn.commit()

    conn.close()


def service_to_dict(row):
    return {
        "id": row["id"],
        "name_fr": row["name_fr"], "name_en": row["name_en"], "name_ht": row["name_ht"],
        "description_fr": row["description_fr"], "description_en": row["description_en"],
        "description_ht": row["description_ht"],
        "icon": row["icon"],
        "image_path": row["image_path"],
        "duration_minutes": row["duration_minutes"],
        "price_htg": row["price_htg"],
        "is_active": bool(row["is_active"]),
    }


SETTINGS_KEYS = ("phone", "address", "doctor_name", "appointment_hours", "logo_image", "hero_image")


def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    values = {r["key"]: r["value"] for r in rows}
    return {k: values.get(k, "") for k in SETTINGS_KEYS}


def update_settings(updates):
    """updates: dict of {key: value}. Only known keys are written."""
    conn = get_db()
    for key, value in updates.items():
        if key in SETTINGS_KEYS:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
    conn.commit()
    conn.close()
