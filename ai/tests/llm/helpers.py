from pathlib import Path

from pydantic import BaseModel

FIXTURES = Path(__file__).parent / "fixtures"
PROMPTS = FIXTURES / "prompts"
OUTPUTS = FIXTURES / "outputs"


class Greeting(BaseModel):
    greeting: str
    tone: str
