from gateway.conversation.agents.tools import add_numbers, default_tools


def test_add_numbers_returns_the_sum() -> None:
    assert add_numbers(2, 3) == 5


def test_default_tools_exposes_add_numbers_as_a_function_tool() -> None:
    tools = default_tools()

    assert [tool.name for tool in tools] == ["add_numbers"]
    assert tools[0](a=2, b=3) == 5
