from flask import Flask, request, redirect, url_for, render_template_string, jsonify, session
from pathlib import Path
from werkzeug.utils import secure_filename
import json
import uuid
import os
import re
import html as html_lib
import urllib.request
import urllib.error
from functools import wraps
from datetime import datetime
from supabase import create_client

BASE = Path(__file__).parent
UPLOADS = BASE / "static" / "uploads"
DATA = BASE / "products.json"
PAYMENT_DATA = BASE / "payment.json"
ORDERS_DATA = BASE / "orders.json"
CONTENT_DATA = BASE / "content.json"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
MEDIA_BUCKET = os.environ.get("SUPABASE_MEDIA_BUCKET", "store-media").strip()
PROOF_BUCKET = os.environ.get("SUPABASE_PROOF_BUCKET", "payment-proofs").strip()

supabase_client = None

UPLOADS.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-in-render")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

IMAGE_ALLOWED = {"png", "jpg", "jpeg", "webp"}
PAYMENT_ALLOWED = {"png", "jpg", "jpeg", "webp"}
CONTENT_ALLOWED = {"png", "jpg", "jpeg", "webp"}

def load_json(path, default):
    if not path.exists():
        path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def get_supabase():
    global supabase_client
    if supabase_client is not None:
        return supabase_client
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        supabase_client = None
    return supabase_client


def cloud_enabled():
    return get_supabase() is not None


def normalize_product(product):
    product = dict(product or {})
    product.setdefault("colors", [])
    product.setdefault("sizes", [])
    product.setdefault("color_photos", {})
    return product


def product_db_row(product):
    return {
        "id": str(product.get("id", "")),
        "name": str(product.get("name", "")),
        "category": str(product.get("category", "Shirts")),
        "price": float(product.get("price", 0) or 0),
        "moq": max(1, int(product.get("moq", 1) or 1)),
        "colors": product.get("colors", []),
        "color_photos": product.get("color_photos", {}),
        "sizes": product.get("sizes", []),
        "description": str(product.get("description", "")),
        "photo": str(product.get("photo", "")),
    }


def load_products():
    client = get_supabase()
    if client:
        try:
            rows = client.table("products").select("*").order("created_at", desc=False).execute().data or []
            return [normalize_product(row) for row in rows]
        except Exception:
            pass
    return load_json(DATA, [])


def save_products(products):
    client = get_supabase()
    if client:
        try:
            existing = client.table("products").select("id").execute().data or []
            existing_ids = {str(row["id"]) for row in existing}
            wanted_ids = {str(product.get("id")) for product in products}
            to_delete = list(existing_ids - wanted_ids)
            if to_delete:
                client.table("products").delete().in_("id", to_delete).execute()
            rows = [product_db_row(product) for product in products]
            if rows:
                client.table("products").upsert(rows, on_conflict="id").execute()
            return
        except Exception:
            pass
    save_json(DATA, products)


def load_payment():
    defaults = {
        "bank_name": "",
        "account_name": "",
        "account_number": "",
        "qr": "",
        "court_delivery_options": []
    }
    client = get_supabase()
    if client:
        try:
            row = client.table("payment_settings").select("*").eq("id", 1).maybe_single().execute().data
            if row:
                defaults.update(row)
            return defaults
        except Exception:
            pass

    local = load_json(PAYMENT_DATA, defaults)
    if not isinstance(local, dict):
        local = {}
    local.setdefault("court_delivery_options", [])
    return local


def save_payment(payment):
    client = get_supabase()
    if client:
        try:
            client.table("payment_settings").upsert({
                "id": 1,
                "bank_name": payment.get("bank_name", ""),
                "account_name": payment.get("account_name", ""),
                "account_number": payment.get("account_number", ""),
                "qr": payment.get("qr", ""),
                "court_delivery_options": payment.get("court_delivery_options", [])
            }, on_conflict="id").execute()
            return
        except Exception:
            pass
    save_json(PAYMENT_DATA, payment)


def load_content():
    defaults = {
        "hero_kicker": "DONUT APPAREL / PICKLEBALL CULTURE",
        "hero_line1": "PICKLEBALL",
        "hero_line2": "LIFESTYLE",
        "hero_line3": "DIFFERENTLY.",
        "hero_subtitle": "APPAREL FOR PLAYERS. BY PLAYERS.",
        "hero_shop_button": "SHOP NOW →",
        "hero_new_button": "NEW DROP",
        "hero_side_text": "PLAY\nWEAR\nBELONG",
        "hero_badge_text": "SAME\nCOURT\nDIFFERENT\nBREED",
        "hero_shirt_text": "Good\nDinks\nOnly",
        "hero_shirt_small": "DONUT APPAREL",
        "hero_photo": "",
        "about_title": "Play Different.",
        "about_text": "DONUT APPAREL is a pickleball lifestyle brand built for players who want their apparel to feel as bold as their game. Premium pieces, strong graphics, and a darker street-sport attitude.",
        "about_photo": "",
        "community_title": "A Bigger Pickleball Community",
        "community_text": "Wear the culture. Represent your court.",
        "community_button": "OUR STORY →",
        "community_photo": "",
        "contact_title": "Contact",
        "contact_text": "For orders, collaborations, and inquiries, send us a message.",
        "contact_email": "",
        "contact_phone": "",
        "contact_address": "Dagupan City, Philippines",
        "contact_facebook": "",
        "contact_instagram": "",
        "contact_tiktok": ""
    }

    client = get_supabase()
    if client:
        try:
            row = client.table("website_content").select("*").eq("id", 1).maybe_single().execute().data
            if row:
                defaults.update(row)
            return defaults
        except Exception:
            pass

    stored = load_json(CONTENT_DATA, defaults)
    if not isinstance(stored, dict):
        stored = {}
    for key, value in defaults.items():
        stored.setdefault(key, value)
    return stored


def save_content(content):
    client = get_supabase()
    if client:
        try:
            payload = dict(content)
            payload["id"] = 1
            payload.pop("updated_at", None)
            client.table("website_content").upsert(payload, on_conflict="id").execute()
            return
        except Exception:
            pass
    save_json(CONTENT_DATA, content)


def load_orders():
    client = get_supabase()
    if client:
        try:
            return client.table("orders").select("*").order("created_at", desc=True).execute().data or []
        except Exception:
            pass
    return load_json(ORDERS_DATA, [])


def save_order(order):
    client = get_supabase()
    if client:
        client.table("orders").insert(order).execute()
        return
    orders = load_json(ORDERS_DATA, [])
    orders.append(order)
    save_json(ORDERS_DATA, orders)


def update_order(order_id, fields):
    client = get_supabase()
    if client:
        client.table("orders").update(fields).eq("id", order_id).execute()
        return
    orders = load_json(ORDERS_DATA, [])
    for order in orders:
        if str(order.get("id")) == str(order_id):
            order.update(fields)
            break
    save_json(ORDERS_DATA, orders)


def storage_save(file_obj, bucket, prefix):
    if not file_obj or not file_obj.filename:
        return ""

    ext = Path(secure_filename(file_obj.filename)).suffix.lower().lstrip(".")
    if ext not in IMAGE_ALLOWED:
        return ""

    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"

    client = get_supabase()
    if client:
        try:
            body = file_obj.read()
            file_obj.stream.seek(0)
            client.storage.from_(bucket).upload(
                filename,
                body,
                file_options={
                    "content-type": getattr(file_obj, "mimetype", None) or "application/octet-stream",
                    "cache-control": "3600",
                    "upsert": "false"
                }
            )
            if bucket == MEDIA_BUCKET:
                return client.storage.from_(bucket).get_public_url(filename)
            return filename
        except Exception:
            return ""

    file_obj.save(UPLOADS / filename)
    return f"/static/uploads/{filename}"


def save_upload(file, allowed, prefix, bucket=None):
    if not file or not file.filename:
        return ""
    ext = Path(secure_filename(file.filename)).suffix.lower().lstrip(".")
    if ext not in allowed:
        return ""
    bucket = bucket or MEDIA_BUCKET
    return storage_save(file, bucket, prefix)


def private_proof_url(path):
    if not path:
        return ""
    value = str(path)
    if value.startswith("http://") or value.startswith("https://"):
        return value

    client = get_supabase()
    if client:
        try:
            result = client.storage.from_(PROOF_BUCKET).create_signed_url(value, 3600)
            if isinstance(result, dict):
                return result.get("signedURL") or result.get("signedUrl") or result.get("signed_url") or ""
        except Exception:
            return ""
    return value if value.startswith("/") else "/" + value


def prepare_admin_orders(orders):
    result = []
    for order in orders:
        item = dict(order)
        item["payment_proof_url"] = private_proof_url(item.get("payment_proof", ""))
        result.append(item)
    return result



def bootstrap_cloud_from_repo():
    """
    Import JSON files that are part of the Git repository into Supabase only
    when the corresponding Supabase table is empty. This is intentionally
    conservative: it never overwrites an existing cloud table.
    """
    client = get_supabase()
    if not client:
        return

    try:
        # Products from products.json
        if not (client.table("products").select("id").limit(1).execute().data or []):
            products = load_json(DATA, [])
            rows = []
            for product in products:
                rows.append(product_db_row(product))
            if rows:
                client.table("products").upsert(rows, on_conflict="id").execute()

        # Payment defaults from payment.json
        if not client.table("payment_settings").select("id").eq("id", 1).maybe_single().execute().data:
            payment = load_json(PAYMENT_DATA, {})
            if payment:
                client.table("payment_settings").upsert({
                    "id": 1,
                    "bank_name": payment.get("bank_name", ""),
                    "account_name": payment.get("account_name", ""),
                    "account_number": payment.get("account_number", ""),
                    "qr": payment.get("qr", ""),
                    "court_delivery_options": payment.get("court_delivery_options", [])
                }, on_conflict="id").execute()

        # Website content from content.json
        if not client.table("website_content").select("id").eq("id", 1).maybe_single().execute().data:
            content = load_json(CONTENT_DATA, {})
            if content:
                payload = dict(content)
                payload["id"] = 1
                client.table("website_content").upsert(payload, on_conflict="id").execute()

        # Orders from orders.json
        if not (client.table("orders").select("id").limit(1).execute().data or []):
            orders = load_json(ORDERS_DATA, [])
            valid = []
            for order in orders:
                item = dict(order)
                item.setdefault("email", "")
                item.setdefault("email_status", "")
                item.setdefault("email_error", "")
                item.setdefault("email_result", "")
                valid.append(item)
            if valid:
                client.table("orders").upsert(valid, on_conflict="id").execute()
    except Exception:
        pass


bootstrap_cloud_from_repo()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_credentials_valid(username, password):
    expected_username = os.environ.get("ADMIN_USERNAME", "").strip()
    expected_password = os.environ.get("ADMIN_PASSWORD", "")
    return bool(
        expected_username and expected_password
        and username == expected_username and password == expected_password
    )


ADMIN_LOGIN_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DONUT APPAREL / Admin Login</title>
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#090909;color:#fff;font-family:Arial,sans-serif}
.box{width:min(420px,92vw);background:#111;border:1px solid #2b2b2b;padding:34px;box-shadow:0 20px 60px #0008}
.logo{font-size:28px;font-weight:900;font-style:italic;letter-spacing:-.06em}
.logo small{display:block;font-size:8px;letter-spacing:.42em;font-style:normal;margin:7px 0 0 4px}
h1{font-size:25px;margin:28px 0 6px}.muted{color:#888;font-size:12px;line-height:1.6}
label{display:block;font-size:10px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;margin-top:18px}
input{width:100%;padding:13px;margin-top:7px;background:#070707;color:#fff;border:1px solid #3a3a3a}
input:focus{outline:1px solid #fff}
button{width:100%;margin-top:22px;padding:14px;border:0;background:#fff;color:#000;font-weight:800;letter-spacing:.14em}
.error{margin-top:16px;padding:11px;border:1px solid #713333;background:#220d0d;color:#ffb5b5;font-size:12px}
</style>
</head>
<body>
<div class="box">
  <div class="logo">DONUT<small>APPAREL</small></div>
  <h1>Admin Login</h1>
  <div class="muted">Sign in to manage products, orders, payments, and website content.</div>
  {% if error %}<div class="error">{{error}}</div>{% endif %}
  <form method="post" action="/admin/login">
    <input type="hidden" name="next" value="{{next}}">
    <label>Username</label>
    <input name="username" autocomplete="username" required>
    <label>Password</label>
    <input name="password" type="password" autocomplete="current-password" required>
    <button type="submit">SIGN IN</button>
  </form>
</div>
</body>
</html>
"""


def build_order_email(order):
    def esc(value):
        return html_lib.escape(str(value or ""))

    rows = []
    for item in order.get("items", []):
        name = esc(item.get("name", "Item"))
        color = esc(item.get("color", ""))
        size = esc(item.get("size", ""))
        qty = esc(item.get("qty", 0))
        price = float(item.get("price", 0) or 0)
        line_total = price * int(item.get("qty", 0) or 0)
        rows.append(
            f"""
            <tr>
              <td style="padding:12px 0;border-bottom:1px solid #e8e8e8;">
                <strong>{name}</strong><br>
                <span style="color:#777;font-size:13px;">{color} / {size} · Qty {qty}</span>
              </td>
              <td style="padding:12px 0;border-bottom:1px solid #e8e8e8;text-align:right;white-space:nowrap;">
                ₱{line_total:,.2f}
              </td>
            </tr>
            """
        )

    items_html = "".join(rows) or '<tr><td colspan="2">No items</td></tr>'
    delivery = esc(order.get("court_delivery", order.get("address", "")))
    return f"""<!doctype html>
<html>
<body style="margin:0;background:#f3f3f1;font-family:Arial,Helvetica,sans-serif;color:#111;">
  <div style="max-width:620px;margin:0 auto;padding:30px 16px;">
    <div style="background:#090909;color:#fff;padding:26px 24px;">
      <div style="font-size:26px;font-weight:900;font-style:italic;letter-spacing:-1px;">DONUT</div>
      <div style="font-size:9px;letter-spacing:5px;margin-top:5px;">APPAREL</div>
    </div>

    <div style="background:#fff;padding:30px 24px;">
      <p style="font-size:11px;letter-spacing:2px;color:#777;text-transform:uppercase;margin:0 0 8px;">Order Received</p>
      <h1 style="font-size:30px;margin:0 0 20px;">Thank you, {esc(order.get("name", ""))}.</h1>

      <div style="background:#f5f5f3;padding:18px;margin-bottom:24px;">
        <div style="font-size:11px;color:#777;letter-spacing:1px;">ORDER NUMBER</div>
        <div style="font-size:24px;font-weight:800;margin-top:5px;">#{esc(order.get("id", ""))}</div>
      </div>

      <h2 style="font-size:18px;margin:0 0 12px;">Order Summary</h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        {items_html}
      </table>

      <div style="display:flex;justify-content:space-between;padding:18px 0;border-bottom:1px solid #222;margin-bottom:18px;">
        <strong>Total</strong>
        <strong>₱{float(order.get("total", 0) or 0):,.2f}</strong>
      </div>

      <p style="margin:10px 0;"><strong>Court Delivery:</strong> {delivery}</p>
      <p style="margin:10px 0;"><strong>Payment:</strong> Proof received — pending verification</p>

      <div style="background:#f5f5f3;padding:16px;margin-top:24px;color:#555;font-size:13px;line-height:1.6;">
        We have received your order and payment screenshot. We will verify your payment and contact you if we need anything else.
      </div>

      <p style="margin-top:28px;font-weight:800;">DONUT APPAREL</p>
      <p style="color:#777;font-size:12px;margin-bottom:0;">PICKLEBALL / SPORTS / STREETWEAR</p>
    </div>
  </div>
</body>
</html>"""


def send_order_email(order):
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_email = os.environ.get("RESEND_FROM_EMAIL", "").strip()

    if not api_key:
        return False, "RESEND_API_KEY is not configured"
    if not from_email:
        return False, "RESEND_FROM_EMAIL is not configured"

    to_email = str(order.get("email", "")).strip()
    if not to_email:
        return False, "Customer email is missing"

    payload = json.dumps({
        "from": from_email,
        "to": [to_email],
        "subject": f"DONUT APPAREL — Order #{order['id']} Received",
        "html": build_order_email(order),
        "tags": [{"name": "category", "value": "order_confirmation"}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": f"order-confirmation-{order['id']}"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace")
            if 200 <= response.status < 300:
                return True, raw[:500]
            return False, f"HTTP {response.status}: {raw[:300]}"
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code}: {raw[:400]}"
    except Exception as exc:
        return False, str(exc)


ADMIN_HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DONUT APPAREL / Admin</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:Arial,sans-serif;background:#f4f4f1;color:#111}
.top{background:#111;color:#fff;padding:20px 6%;display:flex;justify-content:space-between;gap:20px}
main{max-width:1150px;margin:30px auto;padding:0 20px}
.card{background:#fff;padding:25px;border:1px solid #ddd;margin-bottom:25px}
h1,h2{margin-top:0}
label{display:block;font-size:13px;font-weight:bold;margin-top:12px}
input,select,textarea{width:100%;padding:12px;margin:6px 0 10px;border:1px solid #ccc;border-radius:3px}
button{background:#111;color:#fff;border:0;padding:12px 18px;cursor:pointer}
button:hover{opacity:.85}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:22px}
.tab{background:#ddd;color:#111;border-radius:20px;padding:10px 18px}
.tab.active{background:#111;color:#fff}
.tabpanel{display:none}
.tabpanel.active{display:block}
.products{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}
.product{background:#fff;border:1px solid #ddd}
.product img{display:block;width:100%;aspect-ratio:1;object-fit:cover;background:#eee}
.info{padding:14px}
.small{font-size:12px;color:#777;margin-top:6px}
.delete{margin-top:12px;background:#b00020}
.qrpreview{max-width:260px;max-height:260px;object-fit:contain;border:1px solid #ddd;padding:8px;background:#fff}
.order-toolbar{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px}
.order-card{background:#fff;border:1px solid #ddd;padding:18px;margin-bottom:14px}
.order-head{display:flex;justify-content:space-between;gap:15px;align-items:flex-start;flex-wrap:wrap}
.order-total{font-size:18px;font-weight:bold}
.receipt{margin-top:12px}
.receipt img{max-width:220px;max-height:220px;object-fit:contain;border:1px solid #ddd;background:#fff;padding:5px}
.empty{padding:20px;background:#fff;border:1px dashed #ccc;color:#777}
@media(max-width:800px){.products{grid-template-columns:repeat(2,1fr)}.order-toolbar{grid-template-columns:1fr}}
@media(max-width:520px){.products{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="top"><b>DONUT APPAREL / ADMIN</b><span>Cloud: {{ "CONNECTED" if cloud_enabled() else "LOCAL" }} &nbsp; · &nbsp; <a href="/admin/logout" style="color:#fff;text-decoration:none">LOG OUT</a></span></div>
<main>

<div class="tabs">
  <button class="tab active" onclick="showTab('productsTab',this)">PRODUCTS</button>
  <button class="tab" onclick="showTab('ordersTab',this)">ORDERS</button>
  <button class="tab" onclick="showTab('paymentTab',this)">PAYMENT</button>
  <button class="tab" onclick="showTab('websiteTab',this)">WEBSITE</button>
</div>

<section id="productsTab" class="tabpanel active">
<div class="card">
<h2>Add Product</h2>
<form action="/admin/add" method="post" enctype="multipart/form-data">
<label>Product Photo</label>
<input type="file" name="photo" accept="image/png,image/jpeg,image/webp" required>
<label>Product Name</label>
<input name="name" placeholder="e.g. Donut Society Tee" required>
<label>Category</label>
<select name="category">
<option>Shirts</option><option>Polo</option><option>Hoodies</option><option>Shorts</option><option>Accessories</option>
</select>
<label>Price (PHP)</label>
<input name="price" type="number" min="0" step="0.01" required>
<label>MOQ (pieces)</label>
<input name="moq" type="number" min="1" value="1" required>
<label>Colors</label>
<input name="colors" id="productColors" placeholder="Black, White, Maroon">
<p class="small">Enter colors separated by commas. Each color below has its own photo upload. You can select multiple photos for each color.</p>
<div id="colorPhotoInputs"></div>

<label>Sizes</label>
<input name="sizes" placeholder="S, M, L, XL, 2XL">
<label>Description</label>
<textarea name="description" rows="4" placeholder="Product description"></textarea>
<button type="submit">UPLOAD PRODUCT</button>
</form>
</div>

<h2>Current Products</h2>
<div class="products">
{% for p in products %}
<div class="product">
<img src="{{p.photo}}" alt="{{p.name}}">
<div class="info">
<b>{{p.name}}</b>
<div>₱{{"{:,.2f}".format(p.price)}}</div>
<div class="small">MOQ {{p.moq}} PCS · {{p.category}}</div>
<div class="small">{{p.colors|join(", ")}}</div><div class="small">{% if p.color_photos %}{{p.color_photos|length}} color(s) with photos{% endif %}</div>
<div class="small">{{p.sizes|join(", ")}}</div>
<form action="/admin/delete/{{p.id}}" method="post">
<button class="delete">DELETE</button>
</form>
</div>
</div>
{% else %}
<p class="empty">No products yet.</p>
{% endfor %}
</div>
</section>

<section id="ordersTab" class="tabpanel">
<div class="card">
<h2>All Orders</h2>
{% set orders = orders_data %}
<div class="order-toolbar">
<div>
<label>Sort orders</label>
<select id="orderSort" onchange="sortOrders()">
<option value="newest">Date — Newest first</option>
<option value="oldest">Date — Oldest first</option>
<option value="product-az">Product — A to Z</option>
<option value="product-za">Product — Z to A</option>
</select>
</div>
<div>
<label>Filter by product</label>
<select id="productFilter" onchange="sortOrders()">
<option value="">All products</option>
{% set product_names=[] %}
{% for o in orders %}
{% for item in o["items"] %}
{% if item.name not in product_names %}{% set _ = product_names.append(item.name) %}{% endif %}
{% endfor %}
{% endfor %}
{% for name in product_names|sort %}
<option value="{{name|e}}">{{name}}</option>
{% endfor %}
</select>
</div>
</div>

<div id="ordersList">
{% for o in orders %}
<div class="order-card" data-date="{{o.created_at}}" data-products="{% for item in o["items"] %}{{item.name|lower}}{% if not loop.last %}||{% endif %}{% endfor %}">
<div class="order-head">
<div>
<b>Order #{{o.id}}</b>
<div class="small">{{o.created_at}}</div>
</div>
<div class="order-total">₱{{"{:,.2f}".format(o.total if o.total is defined else 0)}}</div>
</div>
<div style="margin-top:10px"><b>{{o.name}}</b> · {{o.phone}}</div>
<div class="small">{{o.email}}</div>
<div class="small">{{o.address}}</div>
<div style="margin-top:10px">
{% for item in o["items"] %}
<div class="small"><b>{{item.name}}</b> · {{item.color}} / {{item.size}} · Qty {{item.qty}}</div>
{% endfor %}
</div>
{% if o.payment_proof %}
<div class="receipt">
<a href="{{o.payment_proof_url}}" target="_blank"><img src="{{o.payment_proof_url}}" alt="Payment receipt"></a>
<div class="small">Payment receipt — click to view full size.</div>
</div>
{% else %}
<div class="small" style="margin-top:12px">No payment receipt uploaded.</div>
{% endif %}
</div>
{% else %}
<p class="empty">No customer orders yet.</p>
{% endfor %}
</div>
</div>
</section>

<section id="paymentTab" class="tabpanel">
<div class="card">
<h2>Payment Method</h2>
<p class="small">Upload your bank/payment QR. Customers will see this during checkout.</p>
<form action="/admin/payment" method="post" enctype="multipart/form-data">
<label>Bank / Payment Name</label>
<input name="bank_name" value="{{payment.bank_name}}" placeholder="e.g. BDO, BPI, GCash, Maya">
<label>Account Name</label>
<input name="account_name" value="{{payment.account_name}}" placeholder="Account name">
<label>Account Number / Mobile Number</label>
<input name="account_number" value="{{payment.account_number}}" placeholder="Account number">

<label>Court Delivery Options</label>
<p class="small">Enter one court/location per line. Customers will see these in the "Court Delivery" dropdown.</p>
<textarea name="court_delivery_options" rows="6" placeholder="Court A&#10;Court B&#10;Court C">{{payment.court_delivery_options|join("\n")}}</textarea>
<label>Payment QR Code</label>
<input type="file" name="qr" accept="image/png,image/jpeg,image/webp">
{% if payment.qr %}
<p class="small">Current QR:</p>
<img class="qrpreview" src="{{payment.qr}}" alt="Payment QR">
{% endif %}
<button type="submit">SAVE PAYMENT METHOD</button>
</form>
</div>
</section>


<section id="websiteTab" class="tabpanel">
<div class="card">
<h2>Website Content</h2>
<p class="small">Edit the customer-facing website here. Hero text and hero photo are included below.</p>

<form id="websiteForm" action="/admin/content" method="post" enctype="multipart/form-data">

<h3>HOMEPAGE HERO</h3>
<label>Hero Kicker</label>
<input name="hero_kicker" value="{{content.hero_kicker}}" placeholder="DONUT APPAREL / PICKLEBALL CULTURE">

<label>Hero Line 1</label>
<input name="hero_line1" value="{{content.hero_line1}}" placeholder="PICKLEBALL">

<label>Hero Line 2</label>
<input name="hero_line2" value="{{content.hero_line2}}" placeholder="LIFESTYLE">

<label>Hero Line 3 / Accent</label>
<input name="hero_line3" value="{{content.hero_line3}}" placeholder="DIFFERENTLY.">

<label>Hero Subtitle</label>
<input name="hero_subtitle" value="{{content.hero_subtitle}}" placeholder="APPAREL FOR PLAYERS. BY PLAYERS.">

<label>Shop Now Button</label>
<input name="hero_shop_button" value="{{content.hero_shop_button}}" placeholder="SHOP NOW →">

<label>New Drop Button</label>
<input name="hero_new_button" value="{{content.hero_new_button}}" placeholder="NEW DROP">

<label>Right-side Hero Text</label>
<textarea name="hero_side_text" rows="4" placeholder="PLAY&#10;WEAR&#10;BELONG">{{content.hero_side_text}}</textarea>

<label>Bottom-right Hero Badge</label>
<textarea name="hero_badge_text" rows="5" placeholder="SAME&#10;COURT&#10;DIFFERENT&#10;BREED">{{content.hero_badge_text}}</textarea>

<label>Center Shirt / Graphic Text</label>
<textarea name="hero_shirt_text" rows="4" placeholder="Good&#10;Dinks&#10;Only">{{content.hero_shirt_text}}</textarea>

<label>Small Text Under Graphic</label>
<input name="hero_shirt_small" value="{{content.hero_shirt_small}}" placeholder="DONUT APPAREL">

<label>Hero Background Photo</label>
<input type="file" name="hero_photo" accept="image/png,image/jpeg,image/webp">
{% if content.hero_photo %}
<p class="small">Current Hero photo:</p>
<img class="qrpreview" src="{{content.hero_photo}}" alt="Hero photo">
{% endif %}

<hr style="border:0;border-top:1px solid #ddd;margin:30px 0">

<h3>ABOUT</h3>
<label>About Title</label>
<input name="about_title" value="{{content.about_title}}" placeholder="Play Different.">
<label>About Text</label>
<textarea name="about_text" rows="5" placeholder="About your brand...">{{content.about_text}}</textarea>
<label>About Photo</label>
<input type="file" name="about_photo" accept="image/png,image/jpeg,image/webp">
{% if content.about_photo %}<p class="small">Current About photo:</p><img class="qrpreview" src="{{content.about_photo}}" alt="About photo">{% endif %}

<h3 style="margin-top:30px">COMMUNITY</h3>
<label>Community Title</label>
<input name="community_title" value="{{content.community_title}}" placeholder="A Bigger Pickleball Community">
<label>Community Text</label>
<textarea name="community_text" rows="4" placeholder="Community text...">{{content.community_text}}</textarea>
<label>Community Button Text</label>
<input name="community_button" value="{{content.community_button}}" placeholder="OUR STORY →">
<label>Community Photo</label>
<input type="file" name="community_photo" accept="image/png,image/jpeg,image/webp">
{% if content.community_photo %}<p class="small">Current Community photo:</p><img class="qrpreview" src="{{content.community_photo}}" alt="Community photo">{% endif %}

<h3 style="margin-top:30px">CONTACT</h3>
<label>Contact Title</label>
<input name="contact_title" value="{{content.contact_title}}" placeholder="Contact">
<label>Contact Free Text</label>
<textarea name="contact_text" rows="5" placeholder="Write anything you want customers to see...">{{content.contact_text}}</textarea>
<label>Email</label>
<input name="contact_email" value="{{content.contact_email}}" placeholder="hello@example.com">
<label>Phone</label>
<input name="contact_phone" value="{{content.contact_phone}}" placeholder="+63 ...">
<label>Address</label>
<input name="contact_address" value="{{content.contact_address}}" placeholder="Dagupan City, Philippines">
<label>Facebook</label>
<input name="contact_facebook" value="{{content.contact_facebook}}" placeholder="Facebook page link">
<label>Instagram</label>
<input name="contact_instagram" value="{{content.contact_instagram}}" placeholder="Instagram link">
<label>TikTok</label>
<input name="contact_tiktok" value="{{content.contact_tiktok}}" placeholder="TikTok link">

<button type="submit" style="margin-top:20px">SAVE WEBSITE CONTENT</button>
</form>
</div>
</section>

</main>
<script>
function rebuildColorPhotoInputs(){
  const input=document.getElementById("productColors");
  const box=document.getElementById("colorPhotoInputs");
  if(!input||!box)return;

  const colors=input.value.split(",").map(x=>x.trim()).filter(Boolean);

  box.innerHTML=colors.length ? colors.map((color,index)=>`
    <div style="border:1px solid #ddd;padding:14px;margin:10px 0;background:#fafafa">
      <div style="font-weight:bold;margin-bottom:5px">${escapeAdmin(color)}</div>
      <div class="small">Photos for ${escapeAdmin(color)} — select multiple files.</div>
      <input type="file"
             name="color_photos_${index}"
             accept="image/png,image/jpeg,image/webp"
             multiple>
    </div>
  `).join("") : "";
}

function escapeAdmin(v){
  return String(v||"").replace(/[&<>"']/g,m=>({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[m]));
}

document.addEventListener("DOMContentLoaded",()=>{
  const colors=document.getElementById("productColors");
  if(colors){
    colors.addEventListener("input",rebuildColorPhotoInputs);
    rebuildColorPhotoInputs();
  }
});
</script>

<script>
function showTab(id, btn){
  document.querySelectorAll('.tabpanel').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}
function sortOrders(){
  const list=document.getElementById('ordersList');
  if(!list) return;
  const sort=document.getElementById('orderSort').value;
  const filter=(document.getElementById('productFilter').value||'').toLowerCase();
  const cards=[...list.querySelectorAll('.order-card')];
  cards.forEach(card=>{
    const products=card.dataset.products||'';
    card.style.display=(!filter || products.split('||').includes(filter))?'':'none';
  });
  cards.sort((a,b)=>{
    if(sort==='newest') return new Date(b.dataset.date)-new Date(a.dataset.date);
    if(sort==='oldest') return new Date(a.dataset.date)-new Date(b.dataset.date);
    const pa=(a.dataset.products||'').split('||')[0]||'';
    const pb=(b.dataset.products||'').split('||')[0]||'';
    return sort==='product-za'?pb.localeCompare(pa):pa.localeCompare(pb);
  });
  cards.forEach(card=>list.appendChild(card));
}
sortOrders();
</script>
</body>
</html>
"""


@app.get("/")
def store():
    path = BASE / "templates" / "store.html"
    return path.read_text(encoding="utf-8")

@app.get("/admin/login")
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin"))
    next_url = request.args.get("next", "/admin")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/admin"
    return render_template_string(ADMIN_LOGIN_HTML, error="", next=next_url)


@app.post("/admin/login")
def admin_login_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    next_url = request.form.get("next") or "/admin"
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/admin"
    if admin_credentials_valid(username, password):
        session["admin_logged_in"] = True
        session["admin_username"] = username
        return redirect(next_url)
    return render_template_string(ADMIN_LOGIN_HTML, error="Invalid username or password.", next=next_url), 401


@app.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.get("/admin")
@login_required
def admin():
    return render_template_string(ADMIN_HTML, products=load_products(), payment=load_payment(), content=load_content(), orders_data=prepare_admin_orders(load_orders()), cloud_enabled=cloud_enabled)

@app.post("/admin/add")
@login_required
def add_product():
    photo = save_upload(request.files.get("photo"), IMAGE_ALLOWED, "product")
    if not photo:
        return "Invalid or missing image. Use PNG, JPG, JPEG, or WEBP.", 400

    def csv_field(name):
        return [x.strip() for x in request.form.get(name, "").split(",") if x.strip()]

    products = load_products()
    colors_list = csv_field("colors")
    color_photos = {}

    for index, color in enumerate(colors_list):
        uploaded_files = request.files.getlist(f"color_photos_{index}")
        saved_urls = []
        for uploaded in uploaded_files:
            saved = save_upload(uploaded, IMAGE_ALLOWED, "product_color")
            if saved:
                saved_urls.append(saved)
        if saved_urls:
            color_photos[color] = saved_urls

    products.append({
        "id": uuid.uuid4().hex,
        "name": request.form["name"].strip(),
        "category": request.form.get("category", "Shirts"),
        "price": float(request.form["price"]),
        "moq": max(1, int(request.form.get("moq", 1))),
        "colors": colors_list,
        "color_photos": color_photos,
        "sizes": csv_field("sizes"),
        "description": request.form.get("description", "").strip(),
        "photo": photo
    })
    save_products(products)
    return redirect(url_for("admin"))

@app.post("/admin/payment")
@login_required
def update_payment():
    payment = load_payment()
    payment["bank_name"] = request.form.get("bank_name", "").strip()
    payment["account_name"] = request.form.get("account_name", "").strip()
    payment["account_number"] = request.form.get("account_number", "").strip()
    payment["court_delivery_options"] = [
        x.strip() for x in request.form.get("court_delivery_options", "").splitlines()
        if x.strip()
    ]

    qr_file = request.files.get("qr")
    if qr_file and qr_file.filename:
        new_qr = save_upload(qr_file, PAYMENT_ALLOWED, "payment_qr")
        if not new_qr:
            return "Invalid QR image. Use PNG, JPG, JPEG, or WEBP.", 400
        old = payment.get("qr", "").lstrip("/")
        old_path = BASE / old
        if old_path.exists():
            try:
                old_path.unlink()
            except Exception:
                pass
        payment["qr"] = new_qr

    save_payment(payment)
    return redirect(url_for("admin"))


@app.post("/admin/content")
@login_required
def update_content():
    content = load_content()

    text_fields = [
        "hero_kicker", "hero_line1", "hero_line2", "hero_line3", "hero_subtitle",
        "hero_shop_button", "hero_new_button", "hero_side_text", "hero_badge_text",
        "hero_shirt_text", "hero_shirt_small",
        "about_title", "about_text",
        "community_title", "community_text", "community_button",
        "contact_title", "contact_text", "contact_email", "contact_phone",
        "contact_address", "contact_facebook", "contact_instagram", "contact_tiktok"
    ]
    for field in text_fields:
        content[field] = request.form.get(field, "").strip()

    for field, prefix in [("hero_photo", "hero"), ("about_photo", "about"), ("community_photo", "community")]:
        uploaded = request.files.get(field)
        if uploaded and uploaded.filename:
            new_photo = save_upload(uploaded, CONTENT_ALLOWED, prefix)
            if not new_photo:
                return "Invalid website image. Use PNG, JPG, JPEG, or WEBP.", 400
            old = content.get(field, "").lstrip("/")
            old_path = BASE / old
            if old_path.exists():
                try:
                    old_path.unlink()
                except Exception:
                    pass
            content[field] = new_photo

    save_content(content)
    return redirect(url_for("admin"))


@app.post("/admin/delete/<pid>")
@login_required
def delete_product(pid):
    products = load_products()
    remaining = []
    for product in products:
        if product["id"] == pid:
            relative = product.get("photo", "").lstrip("/")
            image = BASE / relative
            if image.exists():
                try:
                    image.unlink()
                except Exception:
                    pass
        else:
            remaining.append(product)
    save_products(remaining)
    return redirect(url_for("admin"))

@app.get("/api/health/cloud")
@login_required
def api_cloud_health():
    client = get_supabase()
    if not client:
        return jsonify({"ok": False, "connected": False}), 503
    try:
        client.table("website_content").select("id").eq("id", 1).maybe_single().execute()
        return jsonify({"ok": True, "connected": True})
    except Exception as exc:
        return jsonify({"ok": False, "connected": False, "message": str(exc)}), 503


@app.get("/api/products")
def api_products():
    return jsonify(load_products())

@app.get("/api/payment")
def api_payment():
    return jsonify(load_payment())


@app.get("/api/content")
def api_content():
    return jsonify(load_content())

def valid_ph_mobile(phone):
    """
    Require a Philippine mobile number in local 11-digit format:
    09XXXXXXXXX.
    This validates the format only; it does not verify ownership.
    """
    return bool(re.fullmatch(r"09\d{9}", str(phone or "")))


@app.post("/api/order")
def api_order():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    address = request.form.get("address", "").strip()
    items_raw = request.form.get("items", "").strip()
    proof = request.files.get("payment_proof")

    if not name or not phone or not email or not address or not items_raw:
        return jsonify({"ok": False, "message": "Please complete your name, email, phone, and court delivery location."}), 400

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"ok": False, "message": "Please enter a valid email address."}), 400

    try:
        items = json.loads(items_raw)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid cart data."}), 400

    proof_url = ""
    if proof and proof.filename:
        proof_url = save_upload(proof, IMAGE_ALLOWED, "payment_proof", bucket=PROOF_BUCKET)
        if not proof_url:
            return jsonify({"ok": False, "message": "Invalid payment proof image."}), 400

    total = 0
    for item in items:
        try:
            total += float(item.get("price", 0)) * int(item.get("qty", 0))
        except Exception:
            pass

    order = {
        "id": uuid.uuid4().hex[:10].upper(),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "name": name,
        "phone": phone,
        "email": email,
        "address": address,
        "court_delivery": request.form.get("court_delivery", address),
        "items": items,
        "total": total,
        "payment_proof": proof_url
    }
    try:
        save_order({
            **order,
            "email_status": "",
            "email_error": "",
            "email_result": ""
        })
    except Exception:
        return jsonify({"ok": False, "message": "The order could not be saved. Please try again."}), 500

    email_sent, email_result = send_order_email(order)
    order["email_status"] = "sent" if email_sent else "failed"
    if not email_sent:
        order["email_error"] = email_result
    else:
        order["email_result"] = email_result

    # Save the email delivery state without changing the order itself.
    update_order(order["id"], {
        "email_status": order["email_status"],
        "email_error": order.get("email_error", ""),
        "email_result": order.get("email_result", "")
    })

    return jsonify({
        "ok": True,
        "order_id": order["id"],
        "email_sent": email_sent,
        "email_message": "Order confirmation email sent." if email_sent else "Order received, but confirmation email could not be sent."
    })


    


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
