#!/usr/bin/env python3
import os
import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

# ==========================
# CONFIG
# ==========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
CORS(app)

# SQLite DB in backend folder
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "preprints.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ==========================
# MODELS
# ==========================

class Preprint(db.Model):
    __tablename__ = "preprints"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    abstract = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default="uncategorized")

    # useful later for RVU use-case
    course_code = db.Column(db.String(50))
    authors = db.Column(db.String(255))      # simple comma-separated string for now
    faculty = db.Column(db.String(255))

    pdf_filename = db.Column(db.String(500), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    version = db.Column(db.Integer, default=1)
    doi = db.Column(db.String(100), unique=True, nullable=True)
    status = db.Column(db.String(20), default="submitted")  # submitted / approved / rejected

    def to_dict(self, request_host=None):
        pdf_url = None
        if self.pdf_filename and request_host:
            pdf_url = f"http://{request_host}/api/files/{self.pdf_filename}"

        return {
            "id": self.id,
            "title": self.title,
            "abstract": self.abstract,
            "category": self.category,
            "course_code": self.course_code,
            "authors": self.authors,
            "faculty": self.faculty,
            "pdf_file": pdf_url,
            "uploaded_at": self.uploaded_at.isoformat(),
            "version": self.version,
            "doi": self.doi,
            "status": self.status,
        }


# ==========================
# UTILS
# ==========================

def init_db():
    with app.app_context():
        db.create_all()
        print("✅ Database ready at", app.config["SQLALCHEMY_DATABASE_URI"])


def generate_fake_doi():
    """
    Generates a realistic fake DOI like:
    10.55555/rvu-preprints.202511-0001
    """
    prefix = "10.55555/rvu-preprints"
    now = datetime.datetime.utcnow()
    date_label = f"{now.year}{now.month:02d}"

    # count how many DOIs exist for this month
    month_prefix = f"{prefix}.{date_label}"
    count = Preprint.query.filter(Preprint.doi.like(f"{month_prefix}-%")).count()
    seq = f"{count + 1:04d}"
    return f"{month_prefix}-{seq}"


# ==========================
# ROUTES
# ==========================

@app.route("/api/preprints/", methods=["GET"])
def list_preprints():
    """
    Optional query params:
      - q: search in title/abstract
      - category: filter by category
    """
    q = request.args.get("q", "", type=str).strip().lower()
    category = request.args.get("category", "", type=str).strip().lower()

    query = Preprint.query

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(Preprint.title.ilike(like), Preprint.abstract.ilike(like))
        )

    if category:
        query = query.filter(Preprint.category == category)

    preprints = query.order_by(Preprint.uploaded_at.desc()).all()
    data = [p.to_dict(request_host=request.host) for p in preprints]
    return jsonify(data), 200


@app.route("/api/preprints/<int:pid>/", methods=["GET"])
def get_preprint(pid):
    p = Preprint.query.get_or_404(pid)
    return jsonify(p.to_dict(request_host=request.host)), 200


@app.route("/api/preprints/", methods=["POST"])
def upload_preprint():
    """
    Expects multipart/form-data with fields:
      - title (required)
      - abstract (required)
      - category
      - course_code
      - authors
      - faculty
      - mint_doi (optional, "true"/"false")
      - pdf_file (required file)
    """
    title = request.form.get("title", "").strip()
    abstract = request.form.get("abstract", "").strip()
    category = request.form.get("category", "uncategorized").strip()
    course_code = request.form.get("course_code", "").strip()
    authors = request.form.get("authors", "").strip()
    faculty = request.form.get("faculty", "").strip()
    mint_doi_flag = request.form.get("mint_doi", "false").lower() == "true"

    file = request.files.get("pdf_file")

    if not title or not abstract or not file:
        return jsonify({"error": "Missing required fields: title, abstract, pdf_file"}), 400

    # save PDF
    ts = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    safe_name = f"{ts}_{file.filename.replace(' ', '_')}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)
    file.save(save_path)

    preprint = Preprint(
        title=title,
        abstract=abstract,
        category=category,
        course_code=course_code,
        authors=authors,
        faculty=faculty,
        pdf_filename=safe_name,
    )

    if mint_doi_flag:
        preprint.doi = generate_fake_doi()

    db.session.add(preprint)
    db.session.commit()

    return jsonify(preprint.to_dict(request_host=request.host)), 201


@app.route("/api/preprints/<int:pid>/mint-doi/", methods=["POST"])
def mint_doi(pid):
    preprint = Preprint.query.get_or_404(pid)

    if preprint.doi:
        return jsonify({"doi": preprint.doi}), 200

    preprint.doi = generate_fake_doi()
    db.session.commit()
    return jsonify({"doi": preprint.doi}), 201


@app.route("/api/files/<path:filename>")
def serve_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# (optional) simple health check
@app.route("/api/health")
def health():
    return jsonify({"status": "ok"}), 200


# ==========================
# ENTRYPOINT
# ==========================
if __name__ == "__main__":
    init_db()
    print("🚀 RVU Preprints backend running on http://localhost:5001")
    app.run(host="0.0.0.0", port=5001, debug=True)
