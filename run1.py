import os
import csv
import threading
from pathlib import Path
from flask import Flask, request, send_file, render_template_string, redirect, url_for, flash
from flask import Blueprint
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ================== CONFIG ==================
BASE_DIR = Path(__file__).resolve().parent
CSV_PATH       = "./sample.csv"   # CSV columns: name,mobile
TEMPLATE_PNG   = "./template.png"
OUTPUT_DIR     = "./output"
URL_PREFIX     = "/egc"

# Font
FONT_PATH      = "./LucidaUnicodeCalligraphyBold.ttf"
FONT_NAME      = "LucidaUnicodeCalligraphyBold"
NAME_FONT_SIZE = 125

# Page / background
PAGE_SIZE_MODE = "autosize"   # "letter" or "autosize"
FIT_MODE       = "cover"      # when PAGE_SIZE_MODE="letter": "cover" | "contain" | "stretch"

# Name placement
CENTER_HORIZONTALLY = True
NAME_X_OFFSET       = 0
NAME_Y_ABS          = None
NAME_Y_OFFSET       = 55   # used only if NAME_Y_ABS is None

ALLOW_REGEN_SAME_PDF = False
SECRET_KEY           = "change-this"
# ===========================================

app = Flask(__name__)
app.secret_key = SECRET_KEY
_lock = threading.Lock()

# ---------- utils ----------
def register_font_if_any():
    global FONT_NAME
    if FONT_PATH and os.path.exists(FONT_PATH):
        face = os.path.splitext(os.path.basename(FONT_PATH))[0]
        pdfmetrics.registerFont(TTFont(face, FONT_PATH))
        FONT_NAME = face

def safe_text(v): return "" if v is None else str(v).strip()

def safe_filename(name: str) -> str:
    s = safe_text(name) or "Unnamed"
    for ch in '<>:"\\|?*':
        s = s.replace(ch, "-")
    return s.replace("/", "-").strip()

def normalize_mobile(m: str) -> str:
    if not m: return ""
    s = "".join(ch for ch in str(m) if ch.isdigit())
    if len(s) >= 12 and s.startswith("91"):
        s = s[2:]
    if len(s) > 10:
        s = s[-10:]
    return s

def draw_bg_cover(c, img: ImageReader, page_w, page_h):
    iw, ih = img.getSize()
    scale = max(page_w/iw, page_h/ih)
    dw, dh = iw*scale, ih*scale
    x = (page_w - dw)/2.0
    y = (page_h - dh)/2.0
    c.drawImage(img, x, y, width=dw, height=dh, preserveAspectRatio=True, mask='auto')

def draw_bg_contain(c, img: ImageReader, page_w, page_h):
    iw, ih = img.getSize()
    scale = min(page_w/iw, page_h/ih)
    dw, dh = iw*scale, ih*scale
    x = (page_w - dw)/2.0
    y = (page_h - dh)/2.0
    c.drawImage(img, x, y, width=dw, height=dh, preserveAspectRatio=True, mask='auto')

def draw_bg_stretch(c, img_path, page_w, page_h):
    c.drawImage(img_path, 0, 0, width=page_w, height=page_h,
                preserveAspectRatio=False, mask='auto')

def draw_name(c, name, page_w, page_h):
    text = safe_text(name)
    c.setFont(FONT_NAME, NAME_FONT_SIZE)
    y = NAME_Y_ABS if NAME_Y_ABS is not None else (page_h/2.0 + 215)
    if CENTER_HORIZONTALLY:
        tw = c.stringWidth(text, FONT_NAME, NAME_FONT_SIZE)
        x = (page_w - tw)/2.0 + NAME_X_OFFSET
    else:
        x = 100 + NAME_X_OFFSET
    c.drawString(x, y, text)

def make_certificate_pdf(name: str, mobile: str) -> str:
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    mobile_norm = normalize_mobile(mobile)
    out_base = f"{safe_filename(name)}_{mobile_norm}.pdf"
    out_path = str(Path(OUTPUT_DIR) / out_base)

    if not ALLOW_REGEN_SAME_PDF and os.path.exists(out_path):
        return out_path

    if not os.path.exists(TEMPLATE_PNG):
        raise FileNotFoundError(f"Template not found: {TEMPLATE_PNG}")

    register_font_if_any()

    if PAGE_SIZE_MODE.lower() == "autosize":
        img = ImageReader(TEMPLATE_PNG)
        iw, ih = img.getSize()
        page_w, page_h = float(iw), float(ih)
        c = canvas.Canvas(out_path, pagesize=(page_w, page_h))
        c.drawImage(TEMPLATE_PNG, 0, 0, width=page_w, height=page_h,
                    preserveAspectRatio=False, mask='auto')
    else:
        c = canvas.Canvas(out_path, pagesize=landscape(letter))
        page_w, page_h = landscape(letter)
        img = ImageReader(TEMPLATE_PNG)
        mode = FIT_MODE.lower()
        if mode == "stretch":
            draw_bg_stretch(c, TEMPLATE_PNG, page_w, page_h)
        elif mode == "contain":
            draw_bg_contain(c, img, page_w, page_h)
        else:
            draw_bg_cover(c, img, page_w, page_h)

    draw_name(c, name, page_w, page_h)
    c.showPage()
    c.save()
    return out_path

def load_mobile_set(csv_path: str) -> set:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    s = set()
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if "mobile" not in (reader.fieldnames or []):
            raise ValueError("CSV must include a 'mobile' column.")
        for row in reader:
            m = normalize_mobile(row.get("mobile"))
            if m:
                s.add(m)
    return s

with threading.Lock():
    MOBILE_SET = load_mobile_set(CSV_PATH)

# ---------- HTML (uses url_for with blueprint names) ----------
FORM_HTML = """
<!doctype html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Certificate Download</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f6f7fb;margin:0}
.wrap{max-width:520px;margin:6vh auto;background:#fff;padding:28px;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.08)}
h1{font-size:20px;margin:0 0 12px} p{color:#555;margin-top:0}
label{display:block;margin:14px 0 6px;font-weight:600}
input[type=text],input[type=tel]{width:100%;padding:12px 14px;border:1px solid #dcdde4;border-radius:10px;font-size:16px}
button{margin-top:16px;width:100%;padding:12px 16px;border:0;border-radius:10px;font-weight:700;font-size:16px;background:#3b82f6;color:#fff;cursor:pointer}
button:hover{background:#2563eb}
.msg{margin-top:12px;color:#b91c1c;font-weight:600}.ok{color:#065f46}
.link{display:inline-block;margin-top:14px;text-decoration:none;background:#10b981;color:#fff;padding:10px 14px;border-radius:10px}
small{color:#777}
</style></head><body><div class="wrap">
<h1>Download Your Certificate</h1>
<p>Enter your <b>Name</b> and <b>Mobile</b>. We verify the mobile and print the name you type.</p>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    {% for cat, msg in messages %}
      <div class="msg {{ 'ok' if cat=='ok' else '' }}">{{ msg|safe }}</div>
    {% endfor %}
  {% endif %}
{% endwith %}
<form method="post" action="{{ url_for('egc.verify') }}">
  <label for="name">Full Name (will appear on certificate)</label>
  <input id="name" name="name" type="text" placeholder="e.g., Aarti Sharma" required>
  <label for="mobile">Mobile</label>
  <input id="mobile" name="mobile" type="tel" placeholder="10-digit number" required>
  <button type="submit">Verify & Generate</button>
</form>
<p><small>We match only the mobile number in our records. Duplicate numbers are accepted.</small></p>
</div></body></html>
"""

RESULT_HTML = """
<!doctype html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Certificate Result</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f6f7fb;margin:0}
.wrap{max-width:520px;margin:6vh auto;background:#fff;padding:28px;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.08)}
h1{font-size:20px;margin:0 0 12px} p{color:#444}
.link{display:inline-block;margin-top:14px;text-decoration:none;background:#10b981;color:#fff;padding:10px 14px;border-radius:10px}
.back{display:inline-block;margin-top:14px;text-decoration:none;background:#6366f1;color:#fff;padding:10px 14px;border-radius:10px;margin-left:8px}
</style></head><body><div class="wrap">
<h1>{{ title }}</h1>
<p>{{ message }}</p>
{% if download_url %}
  <a class="link" href="{{ download_url }}">Download PDF</a>
{% endif %}
<a class="back" href="{{ url_for('egc.home') }}">Back</a>
</div></body></html>
"""

# ---------- Blueprint mounted at /egc ----------
bp = Blueprint("egc", __name__, url_prefix=URL_PREFIX)

@bp.get("/")
def home():
    return render_template_string(FORM_HTML)

@bp.post("/verify")
def verify():
    name_input = safe_text(request.form.get("name"))
    mobile_input = normalize_mobile(request.form.get("mobile"))

    if not mobile_input:
        flash("Please enter a valid mobile number.", "err")
        return redirect(url_for('egc.home'))

    if mobile_input not in MOBILE_SET:
        flash("No record found for this mobile number.", "err")
        return redirect(url_for('egc.home'))

    try:
        with _lock:
            _ = make_certificate_pdf(name=name_input, mobile=mobile_input)
        dl_url = url_for('egc.download', name=name_input, mobile=mobile_input)
        flash("Verified! Your certificate is ready.", "ok")
        return render_template_string(
            RESULT_HTML,
            title="Verified ✅",
            message=f"Hi {name_input}, your certificate has been prepared.",
            download_url=dl_url
        )
    except Exception as e:
        flash(f"Error while generating: {e}", "err")
        return render_template_string(
            RESULT_HTML,
            title="Error",
            message="Something went wrong.",
            download_url=None
        )

@bp.get("/download")
def download():
    name = safe_text(request.args.get("name"))
    mobile = normalize_mobile(request.args.get("mobile"))
    if not name or not mobile:
        return "Bad request", 400
    filename = f"{safe_filename(name)}_{mobile}.pdf"
    path = str(Path(OUTPUT_DIR) / filename)
    if not os.path.exists(path):
        with _lock:
            path = make_certificate_pdf(name=name, mobile=mobile)
    return send_file(path, as_attachment=True, download_name=filename)

app.register_blueprint(bp)

# optional health check
@app.get("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    # local dev (production: run via waitress-serve or gunicorn)
    app.run(host="0.0.0.0", port=5000, debug=True)
