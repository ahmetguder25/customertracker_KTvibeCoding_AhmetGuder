from flask import Blueprint

okrs_bp = Blueprint('okrs', __name__, template_folder='templates')

from . import routes
