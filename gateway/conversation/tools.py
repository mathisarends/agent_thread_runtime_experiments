from llmify import FunctionTool


def add_numbers(a: float, b: float) -> float:
    """Add two numbers and return their sum."""
    return a + b


def default_tools() -> tuple[FunctionTool, ...]:
    return (FunctionTool(add_numbers),)
