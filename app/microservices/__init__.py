from flask import Blueprint

microservices_bp = Blueprint('microservices', __name__, template_folder='templates')

from . import routes
