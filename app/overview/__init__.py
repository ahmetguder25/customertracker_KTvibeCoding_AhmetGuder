from flask import Blueprint

overview_bp = Blueprint('overview', __name__, template_folder='templates')

from . import routes
