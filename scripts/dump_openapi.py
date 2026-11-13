import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import api

with open("frontend/openapi.json", "w", encoding="utf-8") as f:
    json.dump(api.app.openapi(), f, indent=2)
print("wrote frontend/openapi.json")
