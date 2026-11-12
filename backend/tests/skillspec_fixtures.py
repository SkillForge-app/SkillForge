from pathlib import Path
import yaml


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "skillspec.yaml"


def load_valid_spec():
    return yaml.safe_load(
        FIXTURE_PATH.read_text(encoding="utf-8-sig")
    )
