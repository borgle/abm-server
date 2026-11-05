import re

from abm_server.mcp.tools import ALL_TOOLS

CJK = re.compile(r"[\u4e00-\u9fff]")


def test_mcp_tool_descriptions_are_english() -> None:
    assert ALL_TOOLS
    for tool in ALL_TOOLS:
        assert tool.description, tool.name
        assert not CJK.search(tool.description), tool.name
        properties = tool.input_schema.get("properties", {})
        for name, spec in properties.items():
            description = spec.get("description")
            if description:
                assert not CJK.search(description), f"{tool.name}.{name}"
