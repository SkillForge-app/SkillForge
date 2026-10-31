
import json

from hypothesis import given, settings, strategies as st

from core.spec.models import AgentDefinition


safe_text = st.text(min_size=1, max_size=40)
optional_text = st.one_of(st.none(), st.text(max_size=80))
json_values = st.recursive(
    st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=30)),
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=15), children, max_size=4),
    ),
    max_leaves=12,
)


@given(
    name=safe_text,
    runtime=st.sampled_from(["python", "node", "container"]),
    entrypoint=safe_text,
    project_name=safe_text,
    description=optional_text,
    tools=st.lists(st.text(max_size=30), max_size=5),
    environment=st.dictionaries(
        st.text(max_size=20),
        st.text(max_size=40),
        max_size=4,
    ),
    config=st.dictionaries(
        st.text(max_size=20),
        json_values,
        max_size=4,
    ),
)
@settings(max_examples=100)
def test_agent_definition_json_round_trip(
    name,
    runtime,
    entrypoint,
    project_name,
    description,
    tools,
    environment,
    config,
):
    original = AgentDefinition(
        agent={
            "name": name,
            "runtime": runtime,
            "entrypoint": entrypoint,
            "description": description,
            "tools": tools,
            "environment": environment,
            "config": config,
        },
        project={"name": project_name},
    )

    json_text = original.model_dump_json()
    restored = AgentDefinition.model_validate_json(json_text)

    assert restored == original
    assert json.loads(json_text) == original.model_dump(mode="json")
