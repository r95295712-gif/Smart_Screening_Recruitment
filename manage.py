#!/usr/bin/env python
import os
import sys

from config.env import load_project_env


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    load_project_env()
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
