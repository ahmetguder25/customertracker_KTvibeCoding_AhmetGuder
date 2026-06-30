from flask import Blueprint

foreignloans_bp = Blueprint('foreignloans', __name__, template_folder='templates')

from . import routes
