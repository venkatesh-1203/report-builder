import os
import tempfile
from pathlib import Path

# Must be set BEFORE the app is imported
_tmp = tempfile.mkdtemp()
os.environ["API_KEY"] = "test-key-123456789"
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp).as_posix()}/test.db"
os.environ["AI_PROVIDER"] = "none"
