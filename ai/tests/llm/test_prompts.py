import json
import shutil
from pathlib import Path

import pytest

from core.llm import PromptFormatError, PromptInputError, PromptNotFound, load_config, load_prompt
from core.llm.errors import PromptLockError
from core.llm.prompt_lock import LOCK_NAME, check_lock, discover, main, update_lock
from core.llm.prompts import PROMPTS_DIR, parse_prompt
from tests.llm.helpers import PROMPTS

HEADER = "---\nid: demo/x\nversion: 1\ndescription: test\ninputs: [a]\n---\n"


# ---------------------------------------------------------------- loading and rendering


def test_load_and_render_system_and_user() -> None:
    prompt = load_prompt("demo/greet", PROMPTS)
    assert prompt.id == "demo/greet"
    assert prompt.version == 1
    assert prompt.meta.model_role == "analysis"
    assert prompt.render({"name": "Ziad", "platform": "Claude"}) == [
        {"role": "system", "content": "You write short greetings for Claude users."},
        {"role": "user", "content": "Say hello to Ziad."},
    ]


def test_user_only_prompt_defaults_to_default_role() -> None:
    prompt = load_prompt("demo/user_only", PROMPTS)
    assert prompt.meta.model_role == "default"
    assert prompt.render({"question": "Why?"}) == [{"role": "user", "content": "Why?"}]


def test_load_is_cached() -> None:
    assert load_prompt("demo/greet", PROMPTS) is load_prompt("demo/greet", PROMPTS)


@pytest.mark.parametrize("prompt_id", ["demo/missing", "nope/greet"])
def test_missing_prompt(prompt_id: str) -> None:
    with pytest.raises(PromptNotFound):
        load_prompt(prompt_id, PROMPTS)


@pytest.mark.parametrize("prompt_id", ["../demo/greet", "demo", "Demo/greet", "demo/greet.md"])
def test_invalid_prompt_id(prompt_id: str) -> None:
    with pytest.raises(PromptNotFound, match="invalid prompt_id"):
        load_prompt(prompt_id, PROMPTS)


def test_render_rejects_missing_and_unknown_inputs() -> None:
    prompt = load_prompt("demo/greet", PROMPTS)
    with pytest.raises(PromptInputError, match=r"missing inputs \['platform'\]"):
        prompt.render({"name": "Ziad"})
    with pytest.raises(PromptInputError, match=r"unknown inputs \['extra'\]"):
        prompt.render({"name": "Ziad", "platform": "Codex", "extra": 1})


def test_render_does_not_evaluate_template_syntax_in_inputs() -> None:
    prompt = load_prompt("demo/user_only", PROMPTS)
    assert prompt.render({"question": "{{ 7 * 7 }}"})[0]["content"] == "{{ 7 * 7 }}"


def test_missing_attribute_is_an_input_error() -> None:
    prompt = parse_prompt(HEADER + "# user\n{{ a.title }}\n", "demo/x")
    with pytest.raises(PromptInputError):
        prompt.render({"a": {}})


def test_crlf_and_lf_files_hash_the_same() -> None:
    text = HEADER + "# user\n{{ a }}\n"
    assert (
        parse_prompt(text, "demo/x").sha256
        == parse_prompt(text.replace("\n", "\r\n"), "demo/x").sha256
    )


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("# user\nhi\n", "frontmatter"),
        ("---\nid: demo/x\nversion: 1\n# user\n", "not closed"),
        (HEADER.replace("demo/x", "demo/y") + "# user\n{{ a }}\n", "does not match path"),
        (HEADER.replace("version: 1", "version: 0") + "# user\n{{ a }}\n", "bad frontmatter"),
        (HEADER.replace("inputs", "colour: red\ninputs") + "# user\n{{ a }}\n", "bad frontmatter"),
        (HEADER.replace("[a]", "[a, a]") + "# user\n{{ a }}\n", "bad frontmatter"),
        (HEADER + "intro\n# user\n{{ a }}\n", "text before"),
        (HEADER + "# system\n{{ a }}\n", "optional '# system'"),
        (HEADER + "# user\n{{ a }}\n# system\nx\n", "optional '# system'"),
        (HEADER + "# system\n\n# user\n{{ a }}\n", "empty"),
        (HEADER + "# user\n{{ a }} {{ b }}\n", r"undeclared inputs \['b'\]"),
        (HEADER + "# user\nno variables\n", r"unused inputs \['a'\]"),
        (HEADER + "# user\n{{ a \n", "template error"),
    ],
)
def test_malformed_prompt_files(text: str, match: str) -> None:
    with pytest.raises(PromptFormatError, match=match):
        parse_prompt(text, "demo/x")


def test_other_headings_stay_in_the_section() -> None:
    prompt = parse_prompt(HEADER + "# user\n## Example\n{{ a }}\n", "demo/x")
    assert prompt.render({"a": "x"})[0]["content"] == "## Example\nx"


# ---------------------------------------------------------------- version lock


@pytest.fixture
def root(tmp_path: Path) -> Path:
    shutil.copytree(PROMPTS, tmp_path / "prompts")
    root = tmp_path / "prompts"
    update_lock(root)
    return root


def bump(path: Path, body: str | None = None, version: int | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    if body is not None:
        text = text.replace("Say hello to", body)
    if version is not None:
        text = text.replace("version: 1", f"version: {version}")
    path.write_text(text, encoding="utf-8")


def test_fresh_lock_is_current(root: Path) -> None:
    lock = json.loads((root / LOCK_NAME).read_text(encoding="utf-8"))
    assert sorted(lock) == ["demo/greet", "demo/user_only"]
    assert check_lock(root) == []


def test_change_without_version_bump_fails_and_blocks_update(root: Path) -> None:
    bump(root / "demo" / "greet.md", body="Wave at")
    assert [p.kind for p in check_lock(root)] == ["not_bumped"]
    with pytest.raises(PromptLockError, match="version is still 1"):
        update_lock(root)


def test_change_with_version_bump_needs_lock_update(root: Path) -> None:
    bump(root / "demo" / "greet.md", body="Wave at", version=2)
    assert [p.kind for p in check_lock(root)] == ["bumped"]
    update_lock(root)
    assert check_lock(root) == []


def test_lowered_version_is_blocking(root: Path) -> None:
    bump(root / "demo" / "greet.md", version=2)
    update_lock(root)
    path = root / "demo" / "greet.md"
    path.write_text(path.read_text(encoding="utf-8").replace("version: 2", "version: 1"), "utf-8")
    assert [p.kind for p in check_lock(root)] == ["version_lowered"]


def test_new_and_removed_prompts(root: Path) -> None:
    (root / "demo" / "user_only.md").rename(root / "demo" / "other.md")
    other = root / "demo" / "other.md"
    other.write_text(other.read_text(encoding="utf-8").replace("demo/user_only", "demo/other"))
    assert {(p.prompt_id, p.kind) for p in check_lock(root)} == {
        ("demo/other", "new"),
        ("demo/user_only", "removed"),
    }


def test_readme_files_are_not_prompts(root: Path) -> None:
    (root / "README.md").write_text("# Prompts\n", encoding="utf-8")
    assert "README" not in discover(root)


def test_cli_check_and_update(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(root)]) == 0
    bump(root / "demo" / "greet.md", body="Wave at")
    assert main(["--root", str(root)]) == 1
    assert main(["--root", str(root), "--update"]) == 1
    bump(root / "demo" / "greet.md", version=2)
    assert main(["--root", str(root), "--update"]) == 0
    assert "version is still 1" in capsys.readouterr().err


# ---------------------------------------------------------------- the repo's real prompts (CI gate)


def test_repo_prompt_lock_is_current() -> None:
    problems = check_lock(PROMPTS_DIR)
    assert not problems, "\n".join(p.message for p in problems)


def test_repo_prompts_use_known_model_roles() -> None:
    roles = load_config().roles
    for prompt_id in discover(PROMPTS_DIR):
        prompt = load_prompt(prompt_id)
        assert prompt.meta.model_role in roles, f"{prompt_id}: unknown role"
