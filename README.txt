THREAD/ APPAREL STORE — CONNECTED V1

This package connects the customer storefront to the product backend.

SETUP
1. Install Python 3.10+
2. Open a terminal in this folder.
3. Run: pip install flask
4. Run: python app.py
5. Open: http://127.0.0.1:5000/

CUSTOMER STORE
http://127.0.0.1:5000/

ADMIN PRODUCT MANAGER
http://127.0.0.1:5000/admin

WORKFLOW
1. Go to Admin.
2. Upload a product photo.
3. Enter product name, category, price, MOQ, colors, sizes and description.
4. Click UPLOAD PRODUCT.
5. The product automatically appears in the customer storefront.

PRODUCT PHOTOS
PNG, JPG, JPEG and WEBP up to 10 MB.
Images are stored in static/uploads/.

PRODUCT DATA
Stored in products.json.

API
GET /api/products
Returns the products used by the customer storefront.
