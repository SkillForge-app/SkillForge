"""Demo seed data (OPS, Codespaces demo), through Backend's own API, never straight into the tables.

devops/demo/demo.sh runs it inside the api container (no host Python needed):
    docker compose ... exec -T api python - < devops/demo/seed.py

Idempotent: a project with the same name is never created twice.
"""

import json
import sys
import urllib.request

API = "http://127.0.0.1:8000/api/v1"
PROJECTS = [
    {
        "name": "SkillForge demo",
        "description": "Seeded by devops/demo/seed.py for the Codespaces demo.",
    },
]


def call(method: str, path: str, body: dict | None = None) -> object:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        API + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main() -> int:
    existing = {project["name"] for project in call("GET", "/projects")}
    for project in PROJECTS:
        if project["name"] in existing:
            print(f"seed: project {project['name']!r} already there")
        else:
            created = call("POST", "/projects", project)
            print(f"seed: created project {created['name']!r} ({created['id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
