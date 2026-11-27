#!/usr/bin/env python
"""Django management for the Nazria REST API (python manage.py runserver | migrate | create_api_client ...)."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nazria_api.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
