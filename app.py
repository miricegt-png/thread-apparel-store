from flask import Flask, request, redirect, url_for, render_template_string, jsonify
from pathlib import Path
from werkzeug.utils import secure_filename
import json
import uuid
from datetime import datetime

BASE = Path(__file__).parent
UPLOADS = BASE / "static" / "uploads"
DATA = BASE / "products.json"
PAYMENT_DATA = BASE / "payment.json"
ORDERS_DATA = BASE / "orders.json"

UPLOADS.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

IMAGE_ALLOWED = {"png", "jpg", "jpeg", "webp"}
PAYMENT_ALLOWED = {"png", "jpg", "jpeg", "webp"}

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

def save_upload(file, allowed, prefix):
    if not file or not file.filename:
        return ""
    ext = Path(secure_filename(file.filename)).suffix.lower().lstrip(".")
    if ext not in allowed:
        return ""
    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
    file.save(UPLOADS / filename)
    return f"/static/uploads/{filename}"

ADMIN_HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>THREAD/ Admin</title>
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
<div class="top"><b>THREAD/ ADMIN</b><span>Store Management</span></div>
<main>

<div class="tabs">
  <button class="tab active" onclick="showTab('productsTab',this)">PRODUCTS</button>
  <button class="tab" onclick="showTab('ordersTab',this)">ORDERS</button>
  <button class="tab" onclick="showTab('paymentTab',this)">PAYMENT</button>
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
{% for item in o.items %}
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
<div class="order-card" data-date="{{o.created_at}}" data-products="{% for item in o.items %}{{item.name|lower}}{% if not loop.last %}||{% endif %}{% endfor %}">
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
{% for item in o.items %}
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

@app.get("/admin")
def admin():
    return render_template_string(ADMIN_HTML, products=load_products(), payment=load_payment(), load_json=load_json, ORDERS_DATA=ORDERS_DATA)

@app.post("/admin/add")
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
def update_payment():
    payment = load_payment()
    payment["bank_name"] = request.form.get("bank_name", "").strip()
    payment["account_name"] = request.form.get("account_name", "").strip()
    payment["account_number"] = request.form.get("account_number", "").strip()

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

@app.post("/admin/delete/<pid>")
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


