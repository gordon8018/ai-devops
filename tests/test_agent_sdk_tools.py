import pytest


def test_read_file_returns_content(tmp_path):
    from packages.agent_sdk.tools.builtin.file_tools import read_file_impl
    test_file = tmp_path / "hello.py"
    test_file.write_text("print('hello')")
    result = read_file_impl(str(test_file), str(tmp_path))
    assert "print('hello')" in result


def test_read_file_rejects_outside_workspace(tmp_path):
    from packages.agent_sdk.tools.builtin.file_tools import read_file_impl
    with pytest.raises(PermissionError):
        read_file_impl("/etc/passwd", str(tmp_path))


def test_write_file_creates_content(tmp_path):
    from packages.agent_sdk.tools.builtin.file_tools import write_file_impl
    target = str(tmp_path / "new.py")
    write_file_impl(target, "x = 1", str(tmp_path))
    assert (tmp_path / "new.py").read_text() == "x = 1"


def test_write_file_rejects_outside_workspace(tmp_path):
    from packages.agent_sdk.tools.builtin.file_tools import write_file_impl
    with pytest.raises(PermissionError):
        write_file_impl("/tmp/evil.py", "bad", str(tmp_path))


def test_run_command_whitelisted(tmp_path):
    from packages.agent_sdk.tools.builtin.command_tools import run_command_impl
    result = run_command_impl("echo hello", str(tmp_path))
    assert "hello" in result


def test_run_command_rejects_non_whitelisted(tmp_path):
    from packages.agent_sdk.tools.builtin.command_tools import run_command_impl
    with pytest.raises(PermissionError):
        run_command_impl("curl http://evil.com", str(tmp_path))


def test_run_command_rejects_shell_metacharacters(tmp_path):
    from packages.agent_sdk.tools.builtin.command_tools import run_command_impl
    with pytest.raises(PermissionError, match="metacharacter"):
        run_command_impl("echo hello; curl http://evil.com", str(tmp_path))


def test_run_command_rejects_pipe(tmp_path):
    from packages.agent_sdk.tools.builtin.command_tools import run_command_impl
    with pytest.raises(PermissionError, match="metacharacter"):
        run_command_impl("echo hello | cat", str(tmp_path))


def test_run_command_rejects_command_substitution(tmp_path):
    from packages.agent_sdk.tools.builtin.command_tools import run_command_impl
    with pytest.raises(PermissionError, match="metacharacter"):
        run_command_impl("echo $(whoami)", str(tmp_path))
