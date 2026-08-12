import os
import time
import uuid
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, request, session, jsonify, send_from_directory, g
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from database import get_db, init_db, service_to_dict

load_dotenv()

app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key-a-changer")

UPLOAD_FOLDER = os.environ.get(
    "UPLOAD_FOLDER", os.path.join(app.root_path, "static", "uploads")
)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 Mo max


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_image(file_storage):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    filename = secure_filename(f"{uuid.uuid4().hex}.{ext}")
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return f"/uploads/{filename}"


# ---------------------------------------------------------------------------
# Limitation des tentatives de connexion admin (anti brute-force).
# En mémoire ici (suffisant pour un seul serveur) ; pour plusieurs workers /
# instances, utiliser Redis (ex. Flask-Limiter + backend Redis) en production.
# ---------------------------------------------------------------------------
LOGIN_ATTEMPTS = {}
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60


def is_locked_out(key):
    entry = LOGIN_ATTEMPTS.get(key)
    if not entry:
        return False
    count, first_attempt = entry
    if time.time() - first_attempt > LOCKOUT_SECONDS:
        LOGIN_ATTEMPTS.pop(key, None)
        return False
    return count >= MAX_ATTEMPTS


def register_failed_attempt(key):
    count, first_attempt = LOGIN_ATTEMPTS.get(key, (0, time.time()))
    if time.time() - first_attempt > LOCKOUT_SECONDS:
        count, first_attempt = 0, time.time()
    LOGIN_ATTEMPTS[key] = (count + 1, first_attempt)


def clear_attempts(key):
    LOGIN_ATTEMPTS.pop(key, None)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Page unique (tout le code front est dans ce seul fichier HTML)
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # Sert les images quel que soit l'emplacement réel du dossier
    # (local static/uploads ou disque persistant monté ailleurs, ex. Render).
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
@app.route("/api/services")
def api_services():
    want_all = request.args.get("all") == "1"
    # La liste complète (y compris services désactivés) est réservée à l'admin connecté.
    if want_all and not session.get("admin_id"):
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()
    if want_all:
        rows = db.execute("SELECT * FROM services ORDER BY id DESC").fetchall()
    else:
        rows = db.execute("SELECT * FROM services WHERE is_active=1 ORDER BY id").fetchall()
    db.close()
    return jsonify([service_to_dict(r) for r in rows])


@app.route("/api/appointments", methods=["POST"])
def api_create_appointment():
    data = request.get_json(force=True, silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    service_id = data.get("service_id") or None
    appt_date = (data.get("appointment_date") or "").strip()
    appt_time = (data.get("appointment_time") or "").strip()
    message = (data.get("message") or "").strip()

    if not (full_name and phone and appt_date and appt_time):
        return jsonify({"error": "missing_fields"}), 400

    db = get_db()
    db.execute("""
        INSERT INTO appointments (full_name, phone, email, service_id, appointment_date,
            appointment_time, message, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'en_attente', ?)
    """, (full_name, phone, email, service_id, appt_date, appt_time, message,
          datetime.utcnow().isoformat()))
    db.commit()
    db.close()
    return jsonify({"ok": True}), 201


@app.route("/api/contact", methods=["POST"])
def api_create_contact():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    subject = (data.get("subject") or "").strip()
    message = (data.get("message") or "").strip()

    if not (name and email and message):
        return jsonify({"error": "missing_fields"}), 400

    db = get_db()
    db.execute("""
        INSERT INTO contact_messages (name, email, phone, subject, message, is_read, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?)
    """, (name, email, phone, subject, message, datetime.utcnow().isoformat()))
    db.commit()
    db.close()
    return jsonify({"ok": True}), 201


# ---------------------------------------------------------------------------
# Authentification admin — vérification du mot de passe UNIQUEMENT côté serveur
# (aucun mot de passe ni hash n'est jamais envoyé au navigateur)
# ---------------------------------------------------------------------------
@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    ip = request.remote_addr or "unknown"
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    # Verrou combiné IP + nom d'utilisateur : ralentit le brute-force
    # sans permettre à un attaquant de bloquer le compte d'un autre.
    lock_key = f"{ip}:{username.lower()}"
    if is_locked_out(lock_key):
        return jsonify({"error": "too_many_attempts"}), 429

    db = get_db()
    user = db.execute("SELECT * FROM admin_users WHERE username=?", (username,)).fetchone()
    db.close()

    if user and check_password_hash(user["password_hash"], password):
        clear_attempts(lock_key)
        session["admin_id"] = user["id"]
        session["admin_username"] = user["username"]
        return jsonify({"ok": True, "username": user["username"]})

    register_failed_attempt(lock_key)
    return jsonify({"error": "invalid_credentials"}), 401


@app.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/admin/session")
def api_admin_session():
    if session.get("admin_id"):
        return jsonify({"authenticated": True, "username": session.get("admin_username")})
    return jsonify({"authenticated": False})


# ---------------------------------------------------------------------------
# API Admin — CRUD services (protégée)
# ---------------------------------------------------------------------------
@app.route("/api/admin/services", methods=["POST"])
@login_required
def api_admin_service_create():
    f = request.form
    image_path = save_uploaded_image(request.files.get("image"))
    now = datetime.utcnow().isoformat()
    db = get_db()
    cur = db.execute("""
        INSERT INTO services (name_fr, name_en, name_ht, description_fr, description_en,
            description_ht, icon, image_path, duration_minutes, price_htg, is_active,
            created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        f.get("name_fr", ""), f.get("name_en", ""), f.get("name_ht", ""),
        f.get("description_fr", ""), f.get("description_en", ""), f.get("description_ht", ""),
        f.get("icon", "stethoscope"), image_path,
        int(f.get("duration_minutes") or 30), int(f.get("price_htg") or 0),
        1 if f.get("is_active") == "1" else 0, now, now,
    ))
    db.commit()
    new_id = cur.lastrowid
    row = db.execute("SELECT * FROM services WHERE id=?", (new_id,)).fetchone()
    db.close()
    return jsonify(service_to_dict(row)), 201


@app.route("/api/admin/services/<int:service_id>", methods=["PUT"])
@login_required
def api_admin_service_update(service_id):
    f = request.form
    db = get_db()
    existing = db.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
    if not existing:
        db.close()
        return jsonify({"error": "not_found"}), 404

    image_path = save_uploaded_image(request.files.get("image")) or existing["image_path"]
    db.execute("""
        UPDATE services SET name_fr=?, name_en=?, name_ht=?, description_fr=?, description_en=?,
            description_ht=?, icon=?, image_path=?, duration_minutes=?, price_htg=?, is_active=?,
            updated_at=?
        WHERE id=?
    """, (
        f.get("name_fr", ""), f.get("name_en", ""), f.get("name_ht", ""),
        f.get("description_fr", ""), f.get("description_en", ""), f.get("description_ht", ""),
        f.get("icon", "stethoscope"), image_path,
        int(f.get("duration_minutes") or 30), int(f.get("price_htg") or 0),
        1 if f.get("is_active") == "1" else 0,
        datetime.utcnow().isoformat(), service_id,
    ))
    db.commit()
    row = db.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
    db.close()
    return jsonify(service_to_dict(row))


@app.route("/api/admin/services/<int:service_id>", methods=["DELETE"])
@login_required
def api_admin_service_delete(service_id):
    db = get_db()
    db.execute("DELETE FROM services WHERE id=?", (service_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API Admin — rendez-vous (protégée)
# ---------------------------------------------------------------------------
@app.route("/api/admin/appointments")
@login_required
def api_admin_appointments():
    db = get_db()
    rows = db.execute("""
        SELECT a.*, s.name_fr AS service_name
        FROM appointments a LEFT JOIN services s ON a.service_id = s.id
        ORDER BY a.created_at DESC
    """).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/appointments/<int:appt_id>", methods=["PATCH"])
@login_required
def api_admin_appointment_update(appt_id):
    data = request.get_json(force=True, silent=True) or {}
    status = data.get("status", "en_attente")
    db = get_db()
    db.execute("UPDATE appointments SET status=? WHERE id=?", (status, appt_id))
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/admin/appointments/<int:appt_id>", methods=["DELETE"])
@login_required
def api_admin_appointment_delete(appt_id):
    db = get_db()
    db.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API Admin — messages de contact (protégée)
# ---------------------------------------------------------------------------
@app.route("/api/admin/messages")
@login_required
def api_admin_messages():
    db = get_db()
    rows = db.execute("SELECT * FROM contact_messages ORDER BY created_at DESC").fetchall()
    db.execute("UPDATE contact_messages SET is_read=1")
    db.commit()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/messages/<int:msg_id>", methods=["DELETE"])
@login_required
def api_admin_message_delete(msg_id):
    db = get_db()
    db.execute("DELETE FROM contact_messages WHERE id=?", (msg_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
