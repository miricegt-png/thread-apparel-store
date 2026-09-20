from flask import Flask, request, redirect, url_for, render_template_string, jsonify, session
from pathlib import Path
from werkzeug.utils import secure_filename
import json
import tempfile
import uuid
import os
import re
import html as html_lib
import csv
import mimetypes
from io import StringIO
import urllib.request
from urllib.parse import quote
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
CATEGORIES_DATA = BASE / "categories.json"
SIZE_CHART_DATA = BASE / "size_chart.json"
MODELS_DATA = BASE / "models.json"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
MEDIA_BUCKET = os.environ.get("SUPABASE_MEDIA_BUCKET", "store-media").strip()
PROOF_BUCKET = os.environ.get("SUPABASE_PROOF_BUCKET", "payment-proofs").strip()

supabase_client = None

UPLOADS.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-in-render")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

IMAGE_ALLOWED = {"png", "jpg", "jpeg", "webp"}
PAYMENT_ALLOWED = {"png", "jpg", "jpeg", "webp"}
CONTENT_ALLOWED = {"png", "jpg", "jpeg", "webp"}
DEFAULT_CATEGORIES = ["Shirts", "Polo", "Accessories"]

DEFAULT_SIZE_CHART = {
    "title": "Size Chart",
    "unit": "INCHES",
    "note": "Add your actual garment measurements in Admin → Size Chart. Measurements may vary slightly by production batch.",
    "rows": [
        {"size": "S", "length": "", "chest": "", "shoulder": ""},
        {"size": "M", "length": "", "chest": "", "shoulder": ""},
        {"size": "L", "length": "", "chest": "", "shoulder": ""},
        {"size": "XL", "length": "", "chest": "", "shoulder": ""},
        {"size": "2XL", "length": "", "chest": "", "shoulder": ""},
    ],
}


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


@app.errorhandler(413)
def request_too_large(_error):
    return "Image upload is too large. Please use images totaling 25 MB or less per upload.", 413


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
    product.setdefault("discount_enabled", False)
    product.setdefault("discount_percent", 0)
    product.setdefault("discount_label", "SALE")
    product.setdefault("is_available", True)
    product.setdefault("order_limit", 0)
    product.setdefault("stock_quantity", 0)
    try:
        product["discount_percent"] = max(0, min(100, float(product.get("discount_percent", 0) or 0)))
    except Exception:
        product["discount_percent"] = 0
    try:
        product["order_limit"] = max(0, int(product.get("order_limit", 0) or 0))
    except Exception:
        product["order_limit"] = 0
    try:
        product["stock_quantity"] = max(0, int(product.get("stock_quantity", 0) or 0))
    except Exception:
        product["stock_quantity"] = 0
    product["is_available"] = bool(product.get("is_available", True))
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
        "discount_enabled": bool(product.get("discount_enabled", False)),
        "discount_percent": max(0, min(100, float(product.get("discount_percent", 0) or 0))),
        "discount_label": str(product.get("discount_label", "SALE") or "SALE"),
        "is_available": bool(product.get("is_available", True)),
        "order_limit": max(0, int(product.get("order_limit", 0) or 0)),
        "stock_quantity": max(0, int(product.get("stock_quantity", 0) or 0)),
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



def product_order_stats(products=None):
    """Count distinct customer orders containing each product."""
    products = products if products is not None else load_products()
    stats = {
        str(p.get("id")): {"order_count": 0, "level": 1, "level_progress": 0, "level_percent": 0}
        for p in products
    }
    by_name = {str(p.get("name", "")).strip().lower(): str(p.get("id")) for p in products}

    try:
        orders = load_orders()
    except Exception:
        orders = []

    for order in orders:
        seen_ids=set()
        items=order.get("items", [])
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            product_id = item.get("id")
            key = str(product_id) if product_id is not None else ""
            if key not in stats:
                name_key = str(item.get("name", "")).strip().lower()
                key = by_name.get(name_key, "")
            if key and key in stats and key not in seen_ids:
                stats[key]["order_count"] += 1
                seen_ids.add(key)

    # 10 orders = one level. The bar advances once per qualifying order.
    for stat in stats.values():
        count=stat["order_count"]
        stat["level"] = 1 if count == 0 else ((count - 1) // 10) + 1
        stat["level_progress"] = 0 if count == 0 else ((count - 1) % 10) + 1
        stat["level_percent"] = stat["level_progress"] * 10

    return stats



def product_stock_stats(products=None):
    """Calculate sold pieces and remaining stock for each product."""
    products = products if products is not None else load_products()
    stats = {str(p.get("id")): {"stock_sold": 0, "stock_left": None, "stock_depleted": False} for p in products}

    by_name = {str(p.get("name", "")).strip().lower(): str(p.get("id")) for p in products}
    try:
        orders = load_orders()
    except Exception:
        orders = []

    for order in orders:
        items = order.get("items", [])
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or "")
            if key not in stats:
                key = by_name.get(str(item.get("name", "")).strip().lower(), "")
            if key not in stats:
                continue
            try:
                qty = max(0, int(item.get("qty", 0) or 0))
            except Exception:
                qty = 0
            stats[key]["stock_sold"] += qty

    for product in products:
        key = str(product.get("id"))
        stock_quantity = max(0, int(product.get("stock_quantity", 0) or 0))
        if stock_quantity > 0:
            left = max(0, stock_quantity - stats[key]["stock_sold"])
            stats[key]["stock_left"] = left
            stats[key]["stock_depleted"] = left <= 0

    return stats


def products_for_display():
    products=load_products()
    order_stats=product_order_stats(products)
    stock_stats=product_stock_stats(products)
    displayed=[]
    for product in products:
        item=dict(product)
        pid=str(product.get("id"))
        item["order_count"]=order_stats.get(pid, {}).get("order_count", 0)
        item["level"]=order_stats.get(pid, {}).get("level", 1)
        item["level_progress"]=order_stats.get(pid, {}).get("level_progress", 0)
        item["level_percent"]=order_stats.get(pid, {}).get("level_percent", 0)
        item["order_limit"]=max(0, int(product.get("order_limit", 0) or 0))
        item["order_limit_reached"]=bool(item["order_limit"] > 0 and item["order_count"] >= item["order_limit"])
        item["order_limit_remaining"]=(max(0, item["order_limit"] - item["order_count"]) if item["order_limit"] > 0 else None)

        sinfo=stock_stats.get(pid, {"stock_sold": 0, "stock_left": None, "stock_depleted": False})
        item["stock_quantity"]=max(0, int(product.get("stock_quantity", 0) or 0))
        item["stock_sold"]=sinfo["stock_sold"]
        item["stock_left"]=sinfo["stock_left"]
        item["stock_depleted"]=sinfo["stock_depleted"]
        displayed.append(item)
    return displayed


def normalize_category_name(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def unique_categories(values):
    out=[]
    seen=set()
    for value in values:
        name=normalize_category_name(value)
        key=name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def load_categories(products=None):
    """Load admin-managed item types, while preserving categories used by existing products."""
    products = products if products is not None else load_products()
    product_categories = [p.get("category", "") for p in products]

    client = get_supabase()
    if client:
        try:
            rows = client.table("product_categories").select("id,name,sort_order").order("sort_order", desc=False).order("name", desc=False).execute().data or []
            managed = [row.get("name", "") for row in rows]
            categories = unique_categories(managed)
            existing_keys = {x.casefold() for x in categories}
            for value in product_categories:
                name = normalize_category_name(value)
                if name and name.casefold() not in existing_keys:
                    categories.append(name)
                    existing_keys.add(name.casefold())
            if categories:
                return categories
            return list(DEFAULT_CATEGORIES)
        except Exception:
            # The table may not exist yet. Keep the storefront/admin usable until SQL is run.
            pass

    local = load_json(CATEGORIES_DATA, DEFAULT_CATEGORIES)
    if not isinstance(local, list):
        local = list(DEFAULT_CATEGORIES)
    categories = unique_categories(local)
    existing_keys = {x.casefold() for x in categories}
    for value in product_categories:
        name = normalize_category_name(value)
        if name and name.casefold() not in existing_keys:
            categories.append(name)
            existing_keys.add(name.casefold())
    return categories or list(DEFAULT_CATEGORIES)


def category_resolve(value, categories):
    wanted = normalize_category_name(value)
    for category in categories:
        if category.casefold() == wanted.casefold():
            return category
    return ""


def add_category_name(name):
    name = normalize_category_name(name)
    if not name:
        return False, "Item type is required."

    categories = load_categories()
    if category_resolve(name, categories):
        return False, "That item type already exists."

    client = get_supabase()
    if client:
        try:
            rows = client.table("product_categories").select("sort_order").execute().data or []
            next_order = max([int(r.get("sort_order", 0) or 0) for r in rows] + [0]) + 1
            client.table("product_categories").insert({"name": name, "sort_order": next_order}).execute()
            return True, "Item type added."
        except Exception as exc:
            return False, f"Could not add item type: {exc}"

    local = load_json(CATEGORIES_DATA, DEFAULT_CATEGORIES)
    if not isinstance(local, list):
        local = list(DEFAULT_CATEGORIES)
    local = unique_categories(local)
    local.append(name)
    save_json(CATEGORIES_DATA, local)
    return True, "Item type added."



def normalize_size_chart(data):
    data = dict(data or {})
    data.setdefault("title", DEFAULT_SIZE_CHART["title"])
    data.setdefault("unit", DEFAULT_SIZE_CHART["unit"])
    data.setdefault("note", DEFAULT_SIZE_CHART["note"])
    rows = data.get("rows")
    if not isinstance(rows, list):
        rows = []
    clean=[]
    for row in rows:
        if not isinstance(row, dict):
            continue
        size=str(row.get("size", "")).strip()
        if not size:
            continue
        clean.append({
            "size": size,
            "length": str(row.get("length", "")).strip(),
            "chest": str(row.get("chest", "")).strip(),
            "shoulder": str(row.get("shoulder", "")).strip(),
        })
    data["rows"] = clean
    data["title"] = str(data.get("title", DEFAULT_SIZE_CHART["title"]) or DEFAULT_SIZE_CHART["title"]).strip()
    data["unit"] = str(data.get("unit", DEFAULT_SIZE_CHART["unit"]) or DEFAULT_SIZE_CHART["unit"]).strip().upper()
    data["note"] = str(data.get("note", DEFAULT_SIZE_CHART["note"]) or "").strip()
    return data


def load_size_chart():
    client = get_supabase()
    if client:
        try:
            row = client.table("size_chart_settings").select("*").eq("id", 1).maybe_single().execute().data
            if row:
                return normalize_size_chart(row)
        except Exception:
            pass

    local = load_json(SIZE_CHART_DATA, DEFAULT_SIZE_CHART)
    if not isinstance(local, dict):
        local = dict(DEFAULT_SIZE_CHART)
    return normalize_size_chart(local)


def save_size_chart(chart):
    chart = normalize_size_chart(chart)
    client = get_supabase()
    if client:
        try:
            client.table("size_chart_settings").upsert({
                "id": 1,
                "title": chart["title"],
                "unit": chart["unit"],
                "note": chart["note"],
                "rows": chart["rows"],
            }, on_conflict="id").execute()
            return
        except Exception:
            pass
    save_json(SIZE_CHART_DATA, chart)


def normalize_model(row):
    row = dict(row or {})
    return {
        "id": str(row.get("id", "")),
        "name": str(row.get("name", "")).strip(),
        "caption": str(row.get("caption", "")).strip(),
        "photo": str(row.get("photo", "")).strip(),
        "sort_order": int(row.get("sort_order", 0) or 0),
        "is_active": bool(row.get("is_active", True)),
    }


def load_models(active_only=False):
    client = get_supabase()
    if client:
        try:
            query = client.table("models").select("*").order("sort_order", desc=False).order("created_at", desc=False)
            if active_only:
                query = query.eq("is_active", True)
            rows = query.execute().data or []
            return [normalize_model(x) for x in rows]
        except Exception:
            pass

    local = load_json(MODELS_DATA, [])
    if not isinstance(local, list):
        local=[]
    models=[normalize_model(x) for x in local]
    if active_only:
        models=[x for x in models if x["is_active"]]
    return models


def save_models(models):
    client = get_supabase()
    if client:
        try:
            existing = client.table("models").select("id").execute().data or []
            existing_ids={str(x.get("id")) for x in existing}
            wanted_ids={str(x.get("id")) for x in models if x.get("id")}
            to_delete=list(existing_ids-wanted_ids)
            if to_delete:
                client.table("models").delete().in_("id", to_delete).execute()
            rows=[]
            for idx, model in enumerate(models):
                rows.append({
                    "id": model.get("id") or uuid.uuid4().hex,
                    "name": model.get("name", ""),
                    "caption": model.get("caption", ""),
                    "photo": model.get("photo", ""),
                    "sort_order": idx,
                    "is_active": bool(model.get("is_active", True)),
                })
            if rows:
                client.table("models").upsert(rows, on_conflict="id").execute()
            return
        except Exception:
            pass
    save_json(MODELS_DATA, models)


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
        "order_notice_enabled": True,
        "order_notice_title": "Before You Place Your Order",
        "order_notice_text": "Please note: orders may take approximately 2–3 weeks to prepare and fulfill. If you need your order sooner, please do not continue.",
        "order_notice_checkbox": "I understand and I’m okay with the 2–3 week timeframe.",
        "order_notice_cancel": "GO BACK",
        "order_notice_continue": "I UNDERSTAND & CONTINUE",
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
        temp_path = None
        try:
            # Save the incoming upload to Render's temporary disk first.
            # Website images are browser-compressed before reaching here.
            suffix = f".{ext}" if ext else ""
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                temp_path = tmp.name
                file_obj.save(tmp)

            file_size = Path(temp_path).stat().st_size
            if file_size > 25 * 1024 * 1024:
                app.logger.warning(
                    "Rejected storage upload: %s is %.2f MB",
                    filename, file_size / (1024 * 1024)
                )
                return ""

            mime = (
                getattr(file_obj, "mimetype", None)
                or mimetypes.guess_type(filename)[0]
                or "application/octet-stream"
            )

            # Supabase Storage REST endpoint. This sends the actual file bytes
            # directly to the Storage API with the server-side secret key.
            storage_url = (
                f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/"
                f"{quote(bucket, safe='')}/{quote(filename, safe='/')}"
            )

            with open(temp_path, "rb") as fh:
                body = fh.read()

            req = urllib.request.Request(
                storage_url,
                data=body,
                headers={
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "apikey": SUPABASE_KEY,
                    "Content-Type": mime,
                    "Cache-Control": "3600",
                    "x-upsert": "false",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=60) as response:
                if not (200 <= response.status < 300):
                    raw = response.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"Storage HTTP {response.status}: {raw[:500]}")

            if bucket == MEDIA_BUCKET:
                return (
                    f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/"
                    f"{quote(bucket, safe='')}/{quote(filename, safe='/')}"
                )
            return filename

        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            app.logger.exception(
                "Supabase Storage HTTP error for bucket=%s file=%s: HTTP %s %s",
                bucket, filename, exc.code, raw[:1000]
            )
            return ""
        except Exception as exc:
            app.logger.exception(
                "Supabase Storage upload failed for bucket=%s file=%s: %s",
                bucket, filename, exc
            )
            return ""
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    # Local fallback for development only.
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
        We have received your order and payment screenshot. Please check your inbox and your spam/junk folder for the order confirmation email.
        Your payment receipt is subject to verification. If the uploaded receipt is invalid or cannot be verified, the order will be deleted.
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
            "User-Agent": "DONUT-APPAREL/1.0",
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
        return False, f"HTTP {exc.code}: {raw[:800]}"
    except Exception as exc:
        return False, str(exc)


EDIT_PRODUCT_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DONUT APPAREL / Edit Product</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:Arial,sans-serif;background:#f4f4f1;color:#111}
.top{background:#111;color:#fff;padding:20px 6%;display:flex;justify-content:space-between;gap:20px}
main{max-width:950px;margin:30px auto;padding:0 20px}
.card{background:#fff;padding:26px;border:1px solid #ddd}
h1{margin:0 0 6px}
.muted,.small{color:#777;font-size:12px;line-height:1.5}
label{display:block;font-size:13px;font-weight:bold;margin-top:16px}
input,textarea,select{width:100%;padding:12px;margin:6px 0 10px;border:1px solid #ccc;border-radius:3px}
button{background:#111;color:#fff;border:0;padding:12px 18px;cursor:pointer}
button.secondary{background:#e5e5e5;color:#111}
.actions{display:flex;gap:10px;margin-top:22px}
.current{margin-top:6px;background:#fafafa;border:1px solid #ddd;padding:12px}
.current img{display:block;width:180px;height:180px;object-fit:cover;background:#eee;margin-top:8px}
.color-box{border:1px solid #ddd;background:#fafafa;padding:14px;margin:12px 0}
.color-title{font-size:14px;font-weight:800;margin-bottom:4px}
.photos{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 12px}
.photos img{width:90px;height:90px;object-fit:cover;border:1px solid #ccc;background:#eee}
.note{padding:12px;background:#f2f2ef;border-left:3px solid #111;margin:16px 0;font-size:12px;line-height:1.5}
</style>
</head>
<body>
<div class="top">
  <b>DONUT APPAREL / ADMIN</b>
  <a href="/admin" style="color:#fff;text-decoration:none">← BACK TO ADMIN</a>
</div>

<main>
  <div class="card">
    <h1>Edit Product</h1>
    <div class="muted">Update product information and replace the photos for each color.</div>

    <div class="note">
      Uploading new photos for a color will <b>replace the photos shown for that color</b>.
      Leaving that color's upload empty keeps its current photos.
    </div>

    <form action="/admin/edit/{{product.id}}" method="post" enctype="multipart/form-data">
      <label>Main Product Photo</label>
      <input type="file" name="photo" accept="image/png,image/jpeg,image/webp">
      {% if product.photo %}
      <div class="current">
        <div class="small">Current main photo:</div>
        <img src="{{product.photo}}" alt="{{product.name}}">
      </div>
      {% endif %}

      <label>Product Name</label>
      <input name="name" value="{{product.name}}" required>

      <label>Category</label>
      <select name="category">
        {% for category in categories %}
        <option value="{{category}}" {% if product.category|lower == category|lower %}selected{% endif %}>{{category}}</option>
        {% endfor %}
      </select>

      <label>Price (PHP)</label>
      <input name="price" type="number" step="0.01" min="0" value="{{product.price}}" required>

      <div style="border:1px solid #ddd;background:#fafafa;padding:14px;margin:12px 0">
        <label style="display:flex;align-items:center;gap:8px;margin-top:0">
          <input type="checkbox" name="discount_enabled" value="1" {% if product.discount_enabled %}checked{% endif %} style="width:auto">
          Put this product on sale
        </label>
        <label>Discount (%)</label>
        <input name="discount_percent" type="number" min="0" max="100" step="1" value="{{product.discount_percent}}" placeholder="10">
        <label>Sale Badge Text</label>
        <input name="discount_label" value="{{product.discount_label}}" maxlength="20" placeholder="SALE or 10% OFF">
      </div>

      <label>MOQ (pieces)</label>
      <input name="moq" type="number" min="1" value="{{product.moq}}" required>

      <label>Product Status</label>
      <select name="is_available">
        <option value="1" {% if product.is_available %}selected{% endif %}>AVAILABLE — customers can order</option>
        <option value="0" {% if not product.is_available %}selected{% endif %}>SOLD OUT — ordering disabled</option>
      </select>

      <label>Order Limit</label>
      <input name="order_limit" type="number" min="0" step="1" value="{{product.order_limit}}" placeholder="0 = unlimited">
      <div class="small">Maximum number of customer orders for this product. 0 = unlimited. Each customer order counts as 1.</div>

      <label>Stock Quantity</label>
      <input name="stock_quantity" type="number" min="0" step="1" value="{{product.stock_quantity}}" placeholder="0 = unlimited">
      <div class="small">Total pieces available across all colors and sizes. 0 = unlimited.</div>

      <label>Colors</label>
      <input name="colors" id="editColors" value="{{product.colors|join(', ')}}" required>
      <div class="small">Enter colors separated by commas. Color photo upload boxes update automatically.</div>

      <div id="editColorPhotos">
      {% for color in product.colors %}
        {% set key = color %}
        <div class="color-box" data-color="{{color|e}}">
          <div class="color-title">{{color}}</div>
          <div class="small">Current photos for {{color}}:</div>
          <div class="photos">
            {% for url in (product.color_photos.get(key, []) if product.color_photos else []) %}
              <img src="{{url}}" alt="{{color}}">
            {% endfor %}
          </div>
          <input type="file" name="color_photos_{{loop.index0}}" accept="image/png,image/jpeg,image/webp" multiple>
          <div class="small">Choose multiple photos to replace the current gallery for this color.</div>
        </div>
      {% endfor %}
      </div>

      <label>Sizes</label>
      <input name="sizes" value="{{product.sizes|join(', ')}}" placeholder="S, M, L, XL, 2XL">

      <label>Description</label>
      <textarea name="description" rows="6">{{product.description}}</textarea>

      <div class="actions">
        <button type="submit">SAVE PRODUCT CHANGES</button>
        <a href="/admin" style="text-decoration:none"><button type="button" class="secondary">CANCEL</button></a>
      </div>
    </form>
  </div>
</main>

<script>
const existingPhotos={{ product.color_photos|tojson }};
const existingColors={{ product.colors|tojson }};

function esc(v){
  return String(v??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));
}
function renderColorUploadBoxes(){
  const input=document.getElementById("editColors");
  const box=document.getElementById("editColorPhotos");
  if(!input||!box)return;

  const colors=input.value.split(",").map(x=>x.trim()).filter(Boolean);

  box.innerHTML=colors.map((color,index)=>{
    let oldKey=existingColors.find(c=>String(c).trim().toLowerCase()===color.toLowerCase());
    let photos=(oldKey && existingPhotos && Array.isArray(existingPhotos[oldKey])) ? existingPhotos[oldKey] : [];
    return `
      <div class="color-box">
        <div class="color-title">${esc(color)}</div>
        <div class="small">Current photos for ${esc(color)}:</div>
        <div class="photos">
          ${photos.map(url=>`<img src="${esc(url)}" alt="${esc(color)}">`).join("")}
          ${photos.length?"" : `<div class="small">No color-specific photos stored.</div>`}
        </div>
        <input type="file" name="color_photos_${index}" accept="image/png,image/jpeg,image/webp" multiple>
        <div class="small">Select multiple photos to replace this color's gallery. Leave empty to keep the current photos.</div>
      </div>`;
  }).join("");
}

document.getElementById("editColors")?.addEventListener("input",renderColorUploadBoxes);
</script>
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
<div class="top"><b>DONUT APPAREL / ADMIN</b><span>Cloud: {{ "CONNECTED" if cloud_enabled() else "LOCAL" }} &nbsp; · &nbsp; <a href="/admin/logout" style="color:#fff;text-decoration:none">LOG OUT</a></span></div>
<main>

<div class="tabs">
  <button class="tab {% if active_tab == 'products' %}active{% endif %}" onclick="showTab('productsTab',this)">PRODUCTS</button>
  <button class="tab {% if active_tab == 'orders' %}active{% endif %}" onclick="showTab('ordersTab',this)">ORDERS</button>
  <button class="tab {% if active_tab == 'payment' %}active{% endif %}" onclick="showTab('paymentTab',this)">PAYMENT</button>
  <button class="tab {% if active_tab == 'website' %}active{% endif %}" onclick="showTab('websiteTab',this)">WEBSITE</button>
  <button class="tab {% if active_tab == 'sizechart' %}active{% endif %}" onclick="showTab('sizeChartTab',this)">SIZE CHART</button>
  <button class="tab {% if active_tab == 'models' %}active{% endif %}" onclick="showTab('modelsTab',this)">MODELS</button>
</div>

<section id="productsTab" class="tabpanel {% if active_tab == 'products' %}active{% endif %}">
<div class="card">
<h2>Manage Item Types</h2>
<p class="small">Add or remove the categories customers see in the shop. An item type cannot be removed while a product is using it.</p>
<form action="/admin/categories/add" method="post" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
  <div style="flex:1;min-width:220px">
    <label style="margin-top:0">New Item Type</label>
    <input name="category_name" placeholder="e.g. Jackets" maxlength="40" required>
  </div>
  <button type="submit">ADD ITEM TYPE</button>
</form>
<div style="display:grid;gap:8px;margin-top:16px">
{% for category in categories %}
  <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;border:1px solid #ddd;padding:10px 12px;background:#fafafa">
    <b>{{category}}</b>
    <form action="/admin/categories/delete" method="post" style="margin:0" onsubmit="return confirm('Remove item type {{category|e}}? This can only be removed when no products use it.');">
      {% if loop.index0 < categories|length %}<input type="hidden" name="category_name" value="{{category}}">{% endif %}
      <button type="submit" class="delete" style="margin:0;padding:9px 12px">REMOVE</button>
    </form>
  </div>
{% endfor %}
</div>
</div>

<div class="card">
<h2>Add Product</h2>
<form action="/admin/add" method="post" enctype="multipart/form-data">
<label>Product Photo</label>
<input type="file" name="photo" accept="image/png,image/jpeg,image/webp" required>
<label>Product Name</label>
<input name="name" placeholder="e.g. Donut Society Tee" required>
<label>Category</label>
<select name="category">
{% for category in categories %}<option value="{{category}}">{{category}}</option>{% endfor %}
</select>
<label>Price (PHP)</label>
<input name="price" type="number" min="0" step="0.01" required>

<div style="border:1px solid #ddd;background:#fafafa;padding:14px;margin:12px 0">
  <label style="display:flex;align-items:center;gap:8px;margin-top:0">
    <input type="checkbox" name="discount_enabled" value="1" style="width:auto">
    Put this product on sale
  </label>
  <label>Discount (%)</label>
  <input name="discount_percent" type="number" min="0" max="100" step="1" value="0" placeholder="10">
  <label>Sale Badge Text</label>
  <input name="discount_label" value="SALE" maxlength="20" placeholder="SALE or 10% OFF">
</div>

<label>MOQ (pieces)</label>
<input name="moq" type="number" min="1" value="1" required>

<label>Product Status</label>
<select name="is_available">
<option value="1" selected>AVAILABLE — customers can order</option>
<option value="0">SOLD OUT — ordering disabled</option>
</select>

<label>Order Limit</label>
<input name="order_limit" type="number" min="0" step="1" value="0" placeholder="0 = unlimited">
<div class="small">Maximum number of customer orders for this product. Enter 0 for unlimited. Each customer order counts as 1 order.</div>

<label>Stock Quantity</label>
<input name="stock_quantity" type="number" min="0" step="1" value="0" placeholder="0 = unlimited">
<div class="small">Total pieces available across all colors and sizes. Enter 0 for unlimited.</div>

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
<div>
  {% if p.discount_enabled and p.discount_percent > 0 %}
    <span style="text-decoration:line-through;color:#999">₱{{"{:,.2f}".format(p.price)}}</span>
    <span style="font-weight:800;color:#c00;margin-left:6px">₱{{"{:,.2f}".format(p.price * (1 - (p.discount_percent / 100)))}}</span>
    <span style="display:inline-block;background:#c00;color:#fff;padding:3px 6px;font-size:10px;margin-left:6px">{{p.discount_label}}</span>
  {% else %}
    ₱{{"{:,.2f}".format(p.price)}}
  {% endif %}
</div>
<div class="small">MOQ {{p.moq}} PCS · {{p.category}}</div>
<div class="small" style="margin-top:6px">
  {% if p.order_limit_reached %}
    <span style="display:inline-block;padding:4px 7px;background:#f5d7d7;color:#9b0000;font-size:10px;font-weight:800;letter-spacing:.06em">ORDER LIMIT REACHED</span>
  {% elif not p.is_available %}
    <span style="display:inline-block;padding:4px 7px;background:#f5d7d7;color:#9b0000;font-size:10px;font-weight:800;letter-spacing:.06em">SOLD OUT</span>
  {% else %}
    <span style="display:inline-block;padding:4px 7px;background:#e8f5e9;color:#176b2c;font-size:10px;font-weight:800;letter-spacing:.06em">AVAILABLE</span>
  {% endif %}
</div>
{% if p.order_limit > 0 %}
<div class="small">Order limit: {{p.order_count}} / {{p.order_limit}}{% if p.order_limit_remaining is not none %} · {{p.order_limit_remaining}} remaining{% endif %}</div>
{% endif %}
{% if p.stock_quantity > 0 %}
<div class="small">Stock: {{p.stock_sold}} / {{p.stock_quantity}} sold · {{p.stock_left}} left</div>
{% else %}
<div class="small">Stock: Unlimited</div>
{% endif %}
<div class="small">{{p.colors|join(", ")}}</div><div class="small">{% if p.color_photos %}{{p.color_photos|length}} color(s) with photos{% endif %}</div>
<div class="small">{{p.sizes|join(", ")}}</div>
<div style="margin-top:10px;border-top:1px solid #eee;padding-top:9px">
  <div class="small"><b>LEVEL {{p.level}}</b> · {{p.level_progress}} / 10 orders</div>
  <div style="height:7px;background:#e5e5e5;margin-top:5px;border-radius:9px;overflow:hidden">
    <div style="width:{{p.level_percent}}%;height:100%;background:#111"></div>
  </div>
  <div class="small" style="margin-top:4px">{{p.order_count}} total orders</div>
</div>
<div class="small" style="margin-top:8px">You can edit product info and re-upload photos.</div>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
<a href="/admin/edit/{{p.id}}" style="text-decoration:none"><button type="button">EDIT</button></a>
<form action="/admin/delete/{{p.id}}" method="post" style="margin:0">
<button class="delete" type="submit">DELETE</button>
</form>
</div>
</div>
</div>
{% else %}
<p class="empty">No products yet.</p>
{% endfor %}
</div>
</section>

<section id="ordersTab" class="tabpanel {% if active_tab == 'orders' %}active{% endif %}">
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
<div style="display:flex;align-items:flex-end">
<button type="button" onclick="exportFilteredOrders()">EXTRACT FILTERED ORDERS</button>
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

<div style="margin-top:16px;padding-top:12px;border-top:1px solid #eee">
  <form action="/admin/orders/delete" method="post" onsubmit="return confirm('Delete Order #{{o.id}} permanently? This will also return its quantities to stock and reduce the product order count.');" style="margin:0">
    <input type="hidden" name="order_id" value="{{o.id}}">
    <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap">
      <div style="flex:1;min-width:220px">
        <label style="margin:0 0 5px">Admin Password Required to Delete</label>
        <input type="password" name="delete_password" placeholder="Enter admin password" required autocomplete="current-password" style="margin:0">
      </div>
      <button class="delete" type="submit" style="width:auto;margin:0">DELETE ORDER</button>
    </div>
  </form>
</div>
</div>
{% else %}
<p class="empty">No customer orders yet.</p>
{% endfor %}
</div>
</div>
</section>

<section id="paymentTab" class="tabpanel {% if active_tab == 'payment' %}active{% endif %}">
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


<section id="websiteTab" class="tabpanel {% if active_tab == 'website' %}active{% endif %}">
<div class="card">
<h2>Website Content</h2>
<p class="small">Edit the customer-facing website here. Hero text and hero photo are included below.</p>


<form id="websiteForm" action="/admin/content" method="post" enctype="multipart/form-data">
<script>
async function compressWebsiteImage(file){
  if(!file || !file.type.startsWith("image/")) return file;

  const MAX_SIDE=1800;
  const TARGET_BYTES=2.5*1024*1024;

  if(file.size <= TARGET_BYTES) return file;

  return new Promise((resolve)=>{
    const img=new Image();
    const url=URL.createObjectURL(file);

    img.onload=()=>{
      URL.revokeObjectURL(url);

      let w=img.naturalWidth;
      let h=img.naturalHeight;
      const scale=Math.min(1,MAX_SIDE/Math.max(w,h));
      w=Math.max(1,Math.round(w*scale));
      h=Math.max(1,Math.round(h*scale));

      const canvas=document.createElement("canvas");
      canvas.width=w;
      canvas.height=h;
      const ctx=canvas.getContext("2d",{alpha:false});
      if(!ctx){
        resolve(file);
        return;
      }

      ctx.drawImage(img,0,0,w,h);

      // Start high enough for a good website image, then reduce quality
      // until the browser produces a reasonably small file.
      let quality=0.82;

      const finish=(blob)=>{
        if(!blob){
          resolve(file);
          return;
        }
        resolve(new File([blob], "website-image-"+Date.now()+".jpg", {
          type:"image/jpeg",
          lastModified:Date.now()
        }));
      };

      const attempt=()=>{
        canvas.toBlob((blob)=>{
          if(!blob){
            finish(null);
            return;
          }
          if(blob.size <= TARGET_BYTES || quality <= 0.55){
            finish(blob);
            return;
          }
          quality-=0.07;
          attempt();
        },"image/jpeg",quality);
      };

      attempt();
    };

    img.onerror=()=>{
      URL.revokeObjectURL(url);
      // If the browser cannot decode the source (for example an unsupported
      // HEIC image), let the server return a clear format error.
      resolve(file);
    };

    img.src=url;
  });
}

document.getElementById("websiteForm")?.addEventListener("submit", async function(e){
  e.preventDefault();

  const submitButton=this.querySelector('button[type="submit"]');
  if(submitButton){
    submitButton.disabled=true;
    submitButton.textContent="COMPRESSING & SAVING...";
  }

  try{
    const formData=new FormData(this);

    for(const field of ["hero_photo","about_photo","community_photo"]){
      const input=this.querySelector(`[name="${field}"]`);
      const current=input && input.files ? input.files[0] : null;
      if(current){
        const compressed=await compressWebsiteImage(current);
        formData.delete(field);
        formData.append(field,compressed,compressed.name);
      }
    }

    const response=await fetch(this.action,{method:"POST",body:formData});
    const html=await response.text();

    if(!response.ok){
      document.open();
      document.write(html);
      document.close();
      return;
    }

    document.open();
    document.write(html);
    document.close();
  }catch(err){
    alert("Unable to upload the website image. Please try again.");
    if(submitButton){
      submitButton.disabled=false;
      submitButton.textContent="SAVE WEBSITE CONTENT";
    }
  }
});
</script>


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

<h3>ORDER CHECKOUT NOTICE</h3>
<label style="display:flex;align-items:center;gap:8px;text-transform:none;letter-spacing:0">
  <input type="checkbox" name="order_notice_enabled" value="1" {% if content.order_notice_enabled %}checked{% endif %} style="width:auto">
  Show notice before customer places an order
</label>

<label>Notice Title</label>
<input name="order_notice_title" value="{{content.order_notice_title}}" placeholder="Before You Place Your Order">

<label>Notice Message</label>
<textarea name="order_notice_text" rows="5" placeholder="Orders may take approximately 2–3 weeks...">{{content.order_notice_text}}</textarea>

<label>Confirmation Checkbox Text</label>
<input name="order_notice_checkbox" value="{{content.order_notice_checkbox}}" placeholder="I understand and I’m okay with the timeframe.">

<label>Back Button Text</label>
<input name="order_notice_cancel" value="{{content.order_notice_cancel}}" placeholder="GO BACK">

<label>Continue Button Text</label>
<input name="order_notice_continue" value="{{content.order_notice_continue}}" placeholder="I UNDERSTAND & CONTINUE">

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



<section id="sizeChartTab" class="tabpanel {% if active_tab == 'sizechart' %}active{% endif %}">
<div class="card">
<h2>Customer Size Chart</h2>
<p class="small">This chart appears from the customer navigation and inside each product's size selector.</p>
<form action="/admin/size-chart" method="post">
<label>Title</label>
<input name="size_chart_title" value="{{size_chart.title}}" placeholder="Size Chart">
<label>Unit</label>
<input name="size_chart_unit" value="{{size_chart.unit}}" placeholder="INCHES">
<label>Measurement Note</label>
<textarea name="size_chart_note" rows="3" placeholder="Measurements may vary slightly.">{{size_chart.note}}</textarea>
<label>Rows</label>
<textarea name="size_chart_rows" rows="10" placeholder="S|27|20|18&#10;M|28|21|19&#10;L|29|22|20&#10;XL|30|23|21">{% for row in size_chart.rows %}{{row.size}}|{{row.length}}|{{row.chest}}|{{row.shoulder}}{% if not loop.last %}&#10;{% endif %}{% endfor %}</textarea>
<div class="small">Use one size per line: <b>SIZE | LENGTH | CHEST | SHOULDER</b></div>
<button type="submit">SAVE SIZE CHART</button>
</form>
</div>
</section>

<section id="modelsTab" class="tabpanel {% if active_tab == 'models' %}active{% endif %}">
<div class="card">
<h2>Models</h2>
<p class="small">Add people wearing DONUT APPAREL. These photos will appear in the customer-facing Models section.</p>
<form action="/admin/models/add" method="post" enctype="multipart/form-data">
<label>Model Photo</label>
<input type="file" name="model_photo" accept="image/png,image/jpeg,image/webp" required>
<label>Model Name / Handle</label>
<input name="model_name" maxlength="80" placeholder="e.g. Ice @mr1ce" required>
<label>Caption / Product Worn</label>
<input name="model_caption" maxlength="160" placeholder="Donut Society Polo — Cream">
<button type="submit">ADD MODEL</button>
</form>
</div>

<div class="card">
<h2>Current Models</h2>
{% if models %}
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px">
{% for model in models %}
<div style="border:1px solid #ddd;background:#fff;overflow:hidden">
<img src="{{model.photo}}" alt="{{model.name}}" style="width:100%;aspect-ratio:3/4;object-fit:contain;background:#f3f3f3;display:block">
<div style="padding:12px">
<b>{{model.name}}</b>
{% if model.caption %}<div class="small" style="margin-top:6px">{{model.caption}}</div>{% endif %}
<form action="/admin/models/delete" method="post" style="margin-top:10px" onsubmit="return confirm('Remove this model from the website?');">
<input type="hidden" name="model_id" value="{{model.id}}">
<button class="delete" type="submit" style="margin:0">REMOVE MODEL</button>
</form>
</div>
</div>
{% endfor %}
</div>
{% else %}
<p class="empty">No models added yet.</p>
{% endif %}
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

  const tabMap={productsTab:'products',ordersTab:'orders',paymentTab:'payment',websiteTab:'website',sizeChartTab:'sizechart',modelsTab:'models'};
  const tab=tabMap[id]||'products';
  const url=new URL(window.location.href);
  url.searchParams.set('tab',tab);
  window.history.replaceState({},'',url.toString());
}
function exportFilteredOrders(){
  const filter=(document.getElementById('productFilter').value||'').trim();
  const url=new URL('/admin/orders/export', window.location.origin);
  if(filter) url.searchParams.set('product', filter);
  window.location.href=url.toString();
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
    active_tab = request.args.get("tab", "products").strip().lower()
    if active_tab not in {"products", "orders", "payment", "website", "sizechart", "models"}:
        active_tab = "products"
    return render_template_string(
        ADMIN_HTML,
        products=products_for_display(),
        payment=load_payment(),
        content=load_content(),
        orders_data=prepare_admin_orders(load_orders()),
        categories=load_categories(),
        size_chart=load_size_chart(),
        models=load_models(),
        cloud_enabled=cloud_enabled,
        active_tab=active_tab,
    )

@app.get("/admin/orders/export")
@login_required
def export_orders():
    product_filter = request.args.get("product", "").strip().lower()
    orders = load_orders()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Order ID", "Date", "Customer Name", "Phone", "Email",
        "Address", "Court Delivery", "Product", "Color", "Size",
        "Quantity", "Order Total", "Payment Proof", "Email Status"
    ])

    for order in orders:
        items = order.get("items", [])
        if not isinstance(items, list):
            continue

        matching_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            if product_filter and name.strip().lower() != product_filter:
                continue
            matching_items.append(item)

        if product_filter and not matching_items:
            continue

        for item in matching_items:
            writer.writerow([
                order.get("id", ""),
                order.get("created_at", ""),
                order.get("name", ""),
                order.get("phone", ""),
                order.get("email", ""),
                order.get("address", ""),
                order.get("court_delivery", ""),
                item.get("name", ""),
                item.get("color", ""),
                item.get("size", ""),
                item.get("qty", ""),
                order.get("total", 0),
                "YES" if order.get("payment_proof") else "NO",
                order.get("email_status", ""),
            ])

    filename = "donut_apparel_orders_filtered.csv" if product_filter else "donut_apparel_orders_all.csv"
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{secure_filename(filename)}"'}
    )


@app.post("/admin/orders/delete")
@login_required
def delete_order():
    order_id = request.form.get("order_id", "").strip()
    delete_password = request.form.get("delete_password", "")

    if not order_id:
        return "Order ID is required.", 400

    # Require the current admin password again for destructive order deletion.
    current_username = session.get("admin_username", "")
    if not admin_credentials_valid(current_username, delete_password):
        return "Incorrect admin password. Order was NOT deleted.", 403

    client = get_supabase()
    if client:
        try:
            result = client.table("orders").delete().eq("id", order_id).execute()
            if not result.data:
                return "Order not found.", 404
            return redirect(url_for("admin", tab="orders"))
        except Exception as exc:
            return f"Could not delete order: {exc}", 500

    orders = load_json(ORDERS_DATA, [])
    original_count = len(orders)
    orders = [o for o in orders if str(o.get("id", "")) != order_id]
    if len(orders) == original_count:
        return "Order not found.", 404
    save_json(ORDERS_DATA, orders)
    return redirect(url_for("admin", tab="orders"))


@app.post("/admin/categories/add")
@login_required
def admin_add_category():
    name = request.form.get("category_name", "")
    ok, message = add_category_name(name)
    if ok:
        return redirect(url_for("admin", tab="products"))
    return message, 400


@app.post("/admin/categories/delete")
@login_required
def admin_delete_category():
    category_id = request.form.get("category_id", "").strip()
    category_name = normalize_category_name(request.form.get("category_name", ""))
    if not category_id and not category_name:
        return "Item type is required.", 400

    products = load_products()
    if category_name:
        in_use = any(normalize_category_name(p.get("category", "")).casefold() == category_name.casefold() for p in products)
        if in_use:
            return "Cannot remove this item type while products are using it. Change those products to another item type first.", 400

    client = get_supabase()
    if client:
        try:
            if category_id:
                result = client.table("product_categories").delete().eq("id", category_id).execute()
            else:
                result = client.table("product_categories").delete().ilike("name", category_name).execute()
            if not result.data:
                return "Item type not found.", 404
            return redirect(url_for("admin", tab="products"))
        except Exception as exc:
            return f"Could not remove item type: {exc}", 500

    local = load_json(CATEGORIES_DATA, DEFAULT_CATEGORIES)
    if not isinstance(local, list):
        local = list(DEFAULT_CATEGORIES)
    before = len(local)
    local = [x for x in local if normalize_category_name(x).casefold() != category_name.casefold()]
    if len(local) == before:
        return "Item type not found.", 404
    save_json(CATEGORIES_DATA, local)
    return redirect(url_for("admin", tab="products"))


@app.post("/admin/size-chart")
@login_required
def admin_save_size_chart():
    chart = {
        "title": request.form.get("size_chart_title", "Size Chart").strip() or "Size Chart",
        "unit": request.form.get("size_chart_unit", "INCHES").strip().upper() or "INCHES",
        "note": request.form.get("size_chart_note", "").strip(),
        "rows": [],
    }

    raw_rows = request.form.get("size_chart_rows", "")
    for raw in raw_rows.splitlines():
        parts=[x.strip() for x in raw.split("|")]
        if not parts or not parts[0]:
            continue
        while len(parts)<4:
            parts.append("")
        chart["rows"].append({
            "size": parts[0],
            "length": parts[1],
            "chest": parts[2],
            "shoulder": parts[3],
        })

    save_size_chart(chart)
    return redirect(url_for("admin", tab="sizechart"))


@app.post("/admin/models/add")
@login_required
def admin_add_model():
    name = request.form.get("model_name", "").strip()
    caption = request.form.get("model_caption", "").strip()
    photo = save_upload(request.files.get("model_photo"), CONTENT_ALLOWED, "model")
    if not name:
        return "Model name is required.", 400
    if not photo:
        return "Model photo is required. Use PNG, JPG, JPEG, or WEBP.", 400

    models=load_models()
    models.append({
        "id": uuid.uuid4().hex,
        "name": name,
        "caption": caption,
        "photo": photo,
        "sort_order": len(models),
        "is_active": True,
    })
    save_models(models)
    return redirect(url_for("admin", tab="models"))


@app.post("/admin/models/delete")
@login_required
def admin_delete_model():
    model_id=request.form.get("model_id", "").strip()
    if not model_id:
        return "Model ID is required.", 400
    models=load_models()
    kept=[m for m in models if str(m.get("id")) != model_id]
    if len(kept)==len(models):
        return "Model not found.", 404
    for idx, model in enumerate(kept):
        model["sort_order"]=idx
    save_models(kept)
    return redirect(url_for("admin", tab="models"))


@app.post("/admin/add")
@login_required
def add_product():
    photo = save_upload(request.files.get("photo"), IMAGE_ALLOWED, "product")
    if not photo:
        return "Invalid or missing image. Use PNG, JPG, JPEG, or WEBP.", 400

    def csv_field(name):
        return [x.strip() for x in request.form.get(name, "").split(",") if x.strip()]

    products = load_products()
    categories = load_categories(products)
    selected_category = category_resolve(request.form.get("category", ""), categories)
    if not selected_category:
        return "Please choose a valid item type.", 400
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

    try:
        regular_price = float(request.form["price"])
        discount_percent = max(0, min(100, float(request.form.get("discount_percent", "0") or 0)))
    except Exception:
        return "Please enter a valid price and discount.", 400

    products.append({
        "id": uuid.uuid4().hex,
        "name": request.form["name"].strip(),
        "category": selected_category,
        "price": regular_price,
        "moq": max(1, int(request.form.get("moq", 1))),
        "colors": colors_list,
        "color_photos": color_photos,
        "sizes": csv_field("sizes"),
        "description": request.form.get("description", "").strip(),
        "photo": photo,
        "discount_enabled": request.form.get("discount_enabled") == "1",
        "discount_percent": discount_percent,
        "discount_label": request.form.get("discount_label", "SALE").strip() or "SALE",
        "is_available": request.form.get("is_available", "1") == "1",
        "order_limit": max(0, int(request.form.get("order_limit", "0") or 0)),
        "stock_quantity": max(0, int(request.form.get("stock_quantity", "0") or 0))
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
        "order_notice_title", "order_notice_text", "order_notice_checkbox",
        "order_notice_cancel", "order_notice_continue",
        "about_title", "about_text",
        "community_title", "community_text", "community_button",
        "contact_title", "contact_text", "contact_email", "contact_phone",
        "contact_address", "contact_facebook", "contact_instagram", "contact_tiktok"
    ]
    for field in text_fields:
        content[field] = request.form.get(field, "").strip()
    content["order_notice_enabled"] = request.form.get("order_notice_enabled") == "1"

    for field, prefix in [("hero_photo", "hero"), ("about_photo", "about"), ("community_photo", "community")]:
        uploaded = request.files.get(field)
        if uploaded and uploaded.filename:
            new_photo = save_upload(uploaded, CONTENT_ALLOWED, prefix)
            if not new_photo:
                return "Website image upload failed. Please use PNG, JPG, JPEG, or WEBP and keep the image under 25 MB. Check Render Logs for the exact Storage error.", 400
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


@app.get("/admin/edit/<pid>")
@login_required
def edit_product(pid):
    products = load_products()
    product = next((p for p in products if str(p.get("id")) == str(pid)), None)
    if not product:
        return "Product not found.", 404

    product.setdefault("colors", [])
    product.setdefault("sizes", [])
    product.setdefault("color_photos", {})
    return render_template_string(EDIT_PRODUCT_HTML, product=product, categories=load_categories(products))


@app.post("/admin/edit/<pid>")
@login_required
def edit_product_save(pid):
    products = load_products()
    product = next((p for p in products if str(p.get("id")) == str(pid)), None)
    if not product:
        return "Product not found.", 404

    def csv_field(name):
        return [x.strip() for x in request.form.get(name, "").split(",") if x.strip()]

    categories = load_categories(products)
    selected_category = category_resolve(request.form.get("category", ""), categories)
    if not selected_category:
        return "Please choose a valid item type.", 400

    try:
        product["name"] = request.form.get("name", "").strip()
        product["category"] = selected_category
        product["price"] = float(request.form.get("price", "0") or 0)
        discount_percent = max(0, min(100, float(request.form.get("discount_percent", "0") or 0)))
        product["discount_enabled"] = request.form.get("discount_enabled") == "1"
        product["discount_percent"] = discount_percent
        product["discount_label"] = request.form.get("discount_label", "SALE").strip() or "SALE"
        product["is_available"] = request.form.get("is_available", "1") == "1"
        product["order_limit"] = max(0, int(request.form.get("order_limit", "0") or 0))
        product["stock_quantity"] = max(0, int(request.form.get("stock_quantity", "0") or 0))
        product["moq"] = max(1, int(request.form.get("moq", "1") or 1))
        new_colors = csv_field("colors")
        product["sizes"] = csv_field("sizes")
        product["description"] = request.form.get("description", "").strip()
    except Exception:
        return "Please check the product values and try again.", 400

    if not product["name"]:
        return "Product name is required.", 400

    # Optional main-photo replacement.
    main_photo = request.files.get("photo")
    if main_photo and main_photo.filename:
        new_main = save_upload(main_photo, IMAGE_ALLOWED, "product")
        if not new_main:
            return "Main product image upload failed. Please use PNG, JPG, JPEG, or WEBP and keep the file under 25 MB.", 400
        product["photo"] = new_main

    old_colors = product.get("colors", [])
    old_color_photos = product.get("color_photos") or {}
    updated_color_photos = {}

    for index, color in enumerate(new_colors):
        old_key = next(
            (k for k in old_color_photos.keys()
             if str(k).strip().lower() == str(color).strip().lower()),
            None
        )

        uploaded_files = request.files.getlist(f"color_photos_{index}")
        uploaded_files = [f for f in uploaded_files if f and f.filename]

        if uploaded_files:
            urls = []
            for uploaded in uploaded_files:
                saved = save_upload(uploaded, IMAGE_ALLOWED, "product_color")
                if saved:
                    urls.append(saved)
            if urls:
                updated_color_photos[color] = urls
            elif old_key is not None:
                updated_color_photos[color] = old_color_photos.get(old_key, [])
        elif old_key is not None:
            updated_color_photos[color] = old_color_photos.get(old_key, [])

    product["colors"] = new_colors
    product["color_photos"] = updated_color_photos

    save_products(products)
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


@app.get("/api/size-chart")
def api_size_chart():
    return jsonify(load_size_chart())


@app.get("/api/models")
def api_models():
    return jsonify(load_models(active_only=True))


@app.get("/api/products")
def api_products():
    return jsonify(products_for_display())


@app.get("/api/categories")
def api_categories():
    return jsonify(load_categories())

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

    # Re-check availability and the order cap on the server. This prevents a
    # stale cart or direct API request from bypassing the storefront lock.
    current_products_list = load_products()
    current_products = {str(p.get("id")): p for p in current_products_list}
    stats = product_order_stats(current_products_list)
    stock_stats = product_stock_stats(current_products_list)
    unavailable = []
    requested_qty_by_product = {}

    for item in items:
        pid = str(item.get("id") or "")
        product = current_products.get(pid)
        if not product:
            unavailable.append(str(item.get("name", "Unknown product")))
            continue

        name = str(product.get("name", item.get("name", "Product")))
        if not product.get("is_available", True):
            unavailable.append(f"{name} (sold out)")
            continue

        try:
            item_qty = max(0, int(item.get("qty", 0) or 0))
        except Exception:
            item_qty = 0
        requested_qty_by_product[pid] = requested_qty_by_product.get(pid, 0) + item_qty

        limit = max(0, int(product.get("order_limit", 0) or 0))
        current_count = stats.get(pid, {}).get("order_count", 0)
        if limit > 0 and current_count >= limit:
            unavailable.append(f"{name} (order limit reached)")

    # Stock is shared across all colors and sizes for a product.
    for pid, requested_qty in requested_qty_by_product.items():
        product = current_products.get(pid)
        if not product:
            continue
        stock_quantity = max(0, int(product.get("stock_quantity", 0) or 0))
        if stock_quantity > 0:
            stock_left = stock_stats.get(pid, {}).get("stock_left", stock_quantity)
            if requested_qty > stock_left:
                name = str(product.get("name", "Product"))
                unavailable.append(f"{name} (only {stock_left} stock left)")

    if unavailable:
        return jsonify({
            "ok": False,
            "message": "The following product(s) cannot be ordered right now: " + ", ".join(unavailable)
        }), 409

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
