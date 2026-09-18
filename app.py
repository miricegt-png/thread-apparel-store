from flask import Flask, request, redirect, url_for, render_template_string
from pathlib import Path
from werkzeug.utils import secure_filename
import json
import uuid

BASE = Path(__file__).parent
UPLOADS = BASE / "static" / "uploads"
DATA = BASE / "products.json"
UPLOADS.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
ALLOWED = {"png", "jpg", "jpeg", "webp"}

def load_products():
    if not DATA.exists():
        DATA.write_text("[]", encoding="utf-8")
    return json.loads(DATA.read_text(encoding="utf-8"))

def save_products(products):
    DATA.write_text(json.dumps(products, indent=2), encoding="utf-8")

def save_photo(file):
    if not file or not file.filename:
        return ""
    ext = Path(secure_filename(file.filename)).suffix.lower().lstrip(".")
    if ext not in ALLOWED:
        return ""
    filename = f"{uuid.uuid4().hex}.{ext}"
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
.top{background:#111;color:#fff;padding:20px 6%;display:flex;justify-content:space-between}
main{max-width:1150px;margin:30px auto;padding:0 20px}
.card{background:#fff;padding:25px;border:1px solid #ddd;margin-bottom:25px}
h1,h2{margin-top:0}
label{display:block;font-size:13px;font-weight:bold;margin-top:12px}
input,select,textarea{width:100%;padding:12px;margin:6px 0 10px;border:1px solid #ccc;border-radius:3px}
button{background:#111;color:#fff;border:0;padding:12px 18px;cursor:pointer}
button:hover{opacity:.85}
.products{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}
.product{background:#fff;border:1px solid #ddd}
.product img{display:block;width:100%;aspect-ratio:1;object-fit:cover;background:#eee}
.info{padding:14px}
.small{font-size:12px;color:#777;margin-top:6px}
.delete{margin-top:12px;background:#b00020}
@media(max-width:800px){.products{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="top"><b>THREAD/ ADMIN</b><span>Product Manager</span></div>
<main>
<div class="card">
<h2>Add Product</h2>
<form action="/admin/add" method="post" enctype="multipart/form-data">
<label>Product Photo</label>
<input type="file" name="photo" accept="image/png,image/jpeg,image/webp" required>

<label>Product Name</label>
<input name="name" placeholder="e.g. Donut Society Tee" required>

<label>Category</label>
<select name="category">
<option>Shirts</option>
<option>Polo</option>
<option>Hoodies</option>
<option>Shorts</option>
<option>Accessories</option>
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

<h2>Products</h2>
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
<p>No products yet.</p>
{% endfor %}
</div>
</main>
</body>
</html>
"""

STORE_HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>THREAD/ Store</title>
<style>
body{margin:0;font-family:Arial;background:#f7f7f5;color:#111}
.nav{padding:22px 6%;background:#111;color:#fff}
.grid{max-width:1150px;margin:35px auto;padding:0 20px;display:grid;grid-template-columns:repeat(4,1fr);gap:18px}
.p{background:#fff}.p img{display:block;width:100%;aspect-ratio:1;object-fit:cover;background:#eee}
.i{padding:15px}.muted{font-size:12px;color:#777}
@media(max-width:800px){.grid{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="nav"><b>THREAD/</b></div>
<div class="grid">
{% for p in products %}
<div class="p">
<img src="{{p.photo}}" alt="{{p.name}}">
<div class="i">
<b>{{p.name}}</b>
<p>₱{{"{:,.2f}".format(p.price)}}</p>
<div class="muted">{{p.category}} · MOQ {{p.moq}} PCS</div>
</div>
</div>
{% endfor %}
</div>
</body>
</html>
"""

@app.get("/")
def store():
    return (BASE / "templates" / "store.html").read_text(encoding="utf-8")

@app.get("/admin")
def admin():
    return render_template_string(ADMIN_HTML, products=load_products())

@app.post("/admin/add")
def add_product():
    photo = save_photo(request.files.get("photo"))
    if not photo:
        return "Invalid or missing image. Use PNG, JPG, JPEG, or WEBP.", 400

    def csv_field(name):
        return [x.strip() for x in request.form.get(name, "").split(",") if x.strip()]

    products = load_products()
    products.append({
        "id": uuid.uuid4().hex,
        "name": request.form["name"].strip(),
        "category": request.form["category"],
        "price": float(request.form["price"]),
        "moq": max(1, int(request.form.get("moq", 1))),
        "colors": csv_field("colors"),
        "sizes": csv_field("sizes"),
        "description": request.form.get("description", "").strip(),
        "photo": photo
    })
    save_products(products)
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
                image.unlink()
        else:
            remaining.append(product)
    save_products(remaining)
    return redirect(url_for("admin"))

if __name__ == "__main__":
    app.run(debug=True)
