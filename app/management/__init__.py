from flask import Blueprint

management_bp = Blueprint('management', __name__, template_folder='templates')

from . import routes
