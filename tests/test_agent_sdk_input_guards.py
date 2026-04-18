def test_boundary_guard_passes_with_valid_constraints():
    from packages.agent_sdk.guardrails.input_guards import BoundaryGuard
    result = BoundaryGuard.check(constraints={"allowedPaths": ["src/"]}, definition_of_done=("Tests pass",))
    assert result.tripwire_triggered is False


def test_boundary_guard_trips_when_constraints_empty():
    from packages.agent_sdk.guardrails.input_guards import BoundaryGuard
    result = BoundaryGuard.check(constraints={}, definition_of_done=())
    assert result.tripwire_triggered is True


def test_sensitive_data_guard_detects_api_key():
    from packages.agent_sdk.guardrails.input_guards import SensitiveDataGuard
    result = SensitiveDataGuard.check("Config: AKIAIOSFODNN7EXAMPLE")
    assert result.tripwire_triggered is False
    assert len(result.warnings) > 0


def test_sensitive_data_guard_passes_clean_input():
    from packages.agent_sdk.guardrails.input_guards import SensitiveDataGuard
    result = SensitiveDataGuard.check("Normal code: x = 1 + 2")
    assert result.tripwire_triggered is False
    assert len(result.warnings) == 0


def test_sensitive_data_guard_detects_github_token():
    from packages.agent_sdk.guardrails.input_guards import SensitiveDataGuard
    result = SensitiveDataGuard.check("token = 'ghp_1234567890abcdefghijklmnopqrstuvwxyz'")
    assert len(result.warnings) > 0
