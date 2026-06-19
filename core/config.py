import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUERY_DIR = os.path.join(BASE_DIR, "queries")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "logos")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg"}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB

PRODUCT_DOCS_FOLDER = os.path.join(BASE_DIR, "static", "product_docs")
CUSTOMER_DOCS_FOLDER = os.path.join(BASE_DIR, "static", "customer_docs")

os.makedirs(PRODUCT_DOCS_FOLDER, exist_ok=True)
os.makedirs(CUSTOMER_DOCS_FOLDER, exist_ok=True)
