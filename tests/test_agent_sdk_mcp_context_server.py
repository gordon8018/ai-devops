def test_context_server_exposes_resources():
    from packages.agent_sdk.tools.mcp_servers.context_server import ContextPackServer
    from packages.shared.domain.models import ContextPack
    pack = ContextPack(pack_id="cp-1", work_item_id="wi-1", repo_scope=("src/main.py",), recent_changes=("abc: fix",))
    server = ContextPackServer(pack)
    resources = server.list_resources()
    names = {r["name"] for r in resources}
    assert "code-graph" in names
    assert "recent-changes" in names
    assert "documentation" in names


def test_context_server_get_resource_returns_data():
    from packages.agent_sdk.tools.mcp_servers.context_server import ContextPackServer
    from packages.shared.domain.models import ContextPack
    pack = ContextPack(pack_id="cp-1", work_item_id="wi-1", recent_changes=("abc123: fix login bug",))
    server = ContextPackServer(pack)
    data = server.get_resource("recent-changes")
    assert "abc123" in data


def test_context_server_get_unknown_resource():
    from packages.agent_sdk.tools.mcp_servers.context_server import ContextPackServer
    from packages.shared.domain.models import ContextPack
    pack = ContextPack(pack_id="cp-1", work_item_id="wi-1")
    server = ContextPackServer(pack)
    data = server.get_resource("nonexistent")
    assert "unknown" in data.lower()
