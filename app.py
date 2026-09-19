from flask import Flask, request, redirect, url_for, render_template_string, jsonify, session
from pathlib import Path
from werkzeug.utils import secure_filename
import json
import uuid
import os
from functools import wraps
from datetime import datetime

BASE = Path(__file__).parent
UPLOADS = BASE / "static" / "uploads"
DATA = BASE / "products.json"
PAYMENT_DATA = BASE / "payment.json"
ORDERS_DATA = BASE / "orders.json"
CONTENT_DATA = BASE / "content.json"

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

def load_products():
    return load_json(DATA, [])

def save_products(products):
    save_json(DATA, products)

def load_payment():
    return load_json(PAYMENT_DATA, {
        "bank_name": "",
        "account_name": "",
        "account_number": "",
        "qr": ""
    })

def save_payment(payment):
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
    stored = load_json(CONTENT_DATA, defaults)
    if not isinstance(stored, dict):
        stored = {}
    for key, value in defaults.items():
        stored.setdefault(key, value)
    return stored

def save_content(content):
    save_json(CONTENT_DATA, content)

def save_upload(file, allowed, prefix):
    if not file or not file.filename:
        return ""
    ext = Path(secure_filename(file.filename)).suffix.lower().lstrip(".")
    if ext not in allowed:
        return ""
    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
    file.save(UPLOADS / filename)
    return f"/static/uploads/{filename}"

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
        and username == expected_username
        and password == expected_password
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
<div class="top"><b>DONUT APPAREL / ADMIN</b><span><a href="/admin/logout" style="color:#fff;text-decoration:none">LOG OUT</a></span></div>
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
<input name="colors" placeholder="Black, White, Maroon">
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
<div class="small">{{p.colors|join(", ")}}</div>
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
{% set orders = load_json(ORDERS_DATA, []) %}
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
<div class="small">{{o.address}}</div>
<div style="margin-top:10px">
{% for item in o["items"] %}
<div class="small"><b>{{item.name}}</b> · {{item.color}} / {{item.size}} · Qty {{item.qty}}</div>
{% endfor %}
</div>
{% if o.payment_proof %}
<div class="receipt">
<a href="{{o.payment_proof}}" target="_blank"><img src="{{o.payment_proof}}" alt="Payment receipt"></a>
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

    return render_template_string(
        ADMIN_LOGIN_HTML,
        error="Invalid username or password.",
        next=next_url
    ), 401


@app.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.get("/admin")
@login_required
def admin():
    return render_template_string(ADMIN_HTML, products=load_products(), payment=load_payment(), content=load_content(), load_json=load_json, ORDERS_DATA=ORDERS_DATA)

@app.post("/admin/add")
@login_required
def add_product():
    photo = save_upload(request.files.get("photo"), IMAGE_ALLOWED, "product")
    if not photo:
        return "Invalid or missing image. Use PNG, JPG, JPEG, or WEBP.", 400

    def csv_field(name):
        return [x.strip() for x in request.form.get(name, "").split(",") if x.strip()]

    products = load_products()
    products.append({
        "id": uuid.uuid4().hex,
        "name": request.form["name"].strip(),
        "category": request.form.get("category", "Shirts"),
        "price": float(request.form["price"]),
        "moq": max(1, int(request.form.get("moq", 1))),
        "colors": csv_field("colors"),
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

@app.get("/api/products")
def api_products():
    return jsonify(load_products())

@app.get("/api/payment")
def api_payment():
    return jsonify(load_payment())


@app.get("/api/content")
def api_content():
    return jsonify(load_content())

@app.post("/api/order")
def api_order():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    address = request.form.get("address", "").strip()
    items_raw = request.form.get("items", "").strip()
    proof = request.files.get("payment_proof")

    if not name or not phone or not address or not items_raw:
        return jsonify({"ok": False, "message": "Please complete your details and cart."}), 400

    try:
        items = json.loads(items_raw)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid cart data."}), 400

    proof_url = ""
    if proof and proof.filename:
        proof_url = save_upload(proof, IMAGE_ALLOWED, "payment_proof")
        if not proof_url:
            return jsonify({"ok": False, "message": "Invalid payment proof image."}), 400

    orders = load_json(ORDERS_DATA, [])
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
        "address": address,
        "court_delivery": request.form.get("court_delivery", address),
        "items": items,
        "total": total,
        "payment_proof": proof_url
    }
    orders.append(order)
    save_json(ORDERS_DATA, orders)

    return jsonify({"ok": True, "order_id": order["id"]})


    


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
