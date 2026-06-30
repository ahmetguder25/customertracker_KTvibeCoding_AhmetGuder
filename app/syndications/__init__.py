from flask import Blueprint

syndications_bp = Blueprint('syndications', __name__, template_folder='templates')

from . import routes
