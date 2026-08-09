"""
WSGI config for pulse_diagnosis project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pulse_diagnosis.settings')

application = get_wsgi_application()
