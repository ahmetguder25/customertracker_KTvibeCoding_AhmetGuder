from flask import Blueprint

work_items_bp = Blueprint('work_items', __name__, template_folder='templates')

from . import routes
