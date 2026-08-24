import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from config import env


class ProjectEnvironmentTests(TestCase):
    def test_loads_values_without_overwriting_process_environment(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "\ufeffFROM_FILE=file-value\n"
                "PRESERVED=file-value\n"
                "export QUOTED=\"quoted value\"\n"
                "SECRET_WITH_EQUALS=part=two\n",
                encoding="utf-8",
            )
            with (
                patch.object(env.Path, "resolve", return_value=Path(directory) / "config" / "env.py"),
                patch.dict(
                    os.environ,
                    {"PRESERVED": "process-value"},
                    clear=True,
                ),
            ):
                env.load_project_env()
                self.assertEqual(os.environ["FROM_FILE"], "file-value")
                self.assertEqual(os.environ["PRESERVED"], "process-value")
                self.assertEqual(os.environ["QUOTED"], "quoted value")
                self.assertEqual(os.environ["SECRET_WITH_EQUALS"], "part=two")
