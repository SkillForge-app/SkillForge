
import json
from pathlib import Path

from backend.app.compiler.platform_schema import PlatformSchema


SCHEMAS_DIR = Path(__file__).parent / "schemas"


def load_platform_schema(platform_name: str) -> PlatformSchema:
    """Load a platform schema from its JSON file."""

    schema_path = SCHEMAS_DIR / f"{platform_name}.json"

    if not schema_path.is_file():
        raise FileNotFoundError(
            f"Platform schema not found: {platform_name}"
        )

    with schema_path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)

    return PlatformSchema(
        name=data["name"],
        instruction_file=data["instruction_file"],
        config_file=data["config_file"]
    )
