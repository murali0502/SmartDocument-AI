"""Write the current API schema for frontend contract generation."""

import json
from pathlib import Path

from smartdoc.app import create_app

destination = Path(__file__).resolve().parents[1] / ".local" / "openapi.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(create_app().openapi()), encoding="utf-8")
