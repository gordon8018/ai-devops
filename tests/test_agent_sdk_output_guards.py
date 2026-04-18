def test_secret_leak_guard_detects_aws_key():
    from packages.agent_sdk.guardrails.output_guards import SecretLeakGuard
    result = SecretLeakGuard.check("config = 'AKIAIOSFODNN7EXAMPLE'")
    assert result.tripwire_triggered is True


def test_secret_leak_guard_passes_clean_output():
    from packages.agent_sdk.guardrails.output_guards import SecretLeakGuard
    result = SecretLeakGuard.check("def hello(): return 'world'")
    assert result.tripwire_triggered is False


def test_code_safety_guard_detects_dangerous_pattern():
    from packages.agent_sdk.guardrails.output_guards import CodeSafetyGuard
    # Testing that the guard detects subprocess shell=True
    result = CodeSafetyGuard.check("subprocess.call(cmd, shell=True)")
    assert result.tripwire_triggered is False
    assert len(result.risks) > 0


def test_code_safety_guard_passes_safe_code():
    from packages.agent_sdk.guardrails.output_guards import CodeSafetyGuard
    result = CodeSafetyGuard.check("x = [1, 2, 3]\nprint(sum(x))")
    assert len(result.risks) == 0


def test_forbidden_path_guard_detects_violation():
    from packages.agent_sdk.guardrails.output_guards import ForbiddenPathGuard
    result = ForbiddenPathGuard.check(
        written_paths=["src/main.py", "secrets/keys.json"], forbidden_paths=["secrets/"],
    )
    assert result.tripwire_triggered is True


def test_forbidden_path_guard_passes_allowed_paths():
    from packages.agent_sdk.guardrails.output_guards import ForbiddenPathGuard
    result = ForbiddenPathGuard.check(
        written_paths=["src/main.py"], forbidden_paths=["secrets/"],
    )
    assert result.tripwire_triggered is False
