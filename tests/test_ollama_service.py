from app import ollama_service


def test_managed_ollama_service_falls_back_to_compose_when_socket_is_missing(
    monkeypatch,
    tmp_path,
) -> None:
    compose_file = tmp_path / "docker-compose.ollama.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    commands = []
    ready_checks = iter([False, True, True])

    monkeypatch.setenv("CONVERSATION_AI_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("CONVERSATION_AI_BASE_URL", "http://host.docker.internal:11434/v1")
    monkeypatch.setenv("OLLAMA_COMPOSE_FILE", str(compose_file))
    monkeypatch.setenv("OLLAMA_MANAGE_SERVICE", "true")
    monkeypatch.setenv("OLLAMA_SHUTDOWN_WHEN_DONE", "true")
    monkeypatch.setenv("OLLAMA_PULL_MODEL_WHEN_MISSING", "true")

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    def fake_ready(base_url: str) -> bool:
        assert base_url == "http://host.docker.internal:11434/api"
        return next(ready_checks)

    model_pulled = False

    def fake_list_local_models(*, base_url: str, request_timeout: float) -> dict:
        assert base_url == "http://host.docker.internal:11434/api"
        if model_pulled:
            return {"models": [{"name": "qwen2.5:7b"}]}
        return {"models": []}

    def fake_pull_model(*, base_url: str, model_name: str) -> None:
        nonlocal model_pulled
        assert base_url == "http://host.docker.internal:11434/api"
        assert model_name == "qwen2.5:7b"
        model_pulled = True

    def fake_runner(command, **kwargs):
        commands.append(command)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(ollama_service, "_is_ollama_ready", fake_ready)
    monkeypatch.setattr(ollama_service, "_list_local_models", fake_list_local_models)
    monkeypatch.setattr(ollama_service, "_pull_model", fake_pull_model)
    monkeypatch.setattr(ollama_service, "_docker_socket_available", lambda socket_path: False)
    monkeypatch.setattr(ollama_service.asyncio, "to_thread", fake_to_thread)

    async def run_context() -> None:
        async with ollama_service.managed_ollama_service(
            enabled=True,
            runner=fake_runner,
            sleeper=lambda _: None,
        ):
            pass

    import asyncio

    asyncio.run(run_context())

    assert commands == [
        ["docker", "compose", "-f", str(compose_file), "up", "-d", "ollama"],
        ["docker", "compose", "-f", str(compose_file), "down"],
    ]
    assert model_pulled is True


def test_managed_ollama_service_uses_docker_api_when_socket_is_available(
    monkeypatch,
) -> None:
    events = []
    ready_checks = iter([False, True, True])
    model_pulled = False

    monkeypatch.setenv("CONVERSATION_AI_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("CONVERSATION_AI_BASE_URL", "http://host.docker.internal:11434/v1")
    monkeypatch.setenv("OLLAMA_MANAGE_SERVICE", "true")
    monkeypatch.setenv("OLLAMA_SHUTDOWN_WHEN_DONE", "true")
    monkeypatch.setenv("OLLAMA_PULL_MODEL_WHEN_MISSING", "true")

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    def fake_ready(base_url: str) -> bool:
        assert base_url == "http://host.docker.internal:11434/api"
        return next(ready_checks)

    def fake_start(config) -> None:
        events.append(("start", config.container_name, config.image, config.volume))

    def fake_stop(config) -> None:
        events.append(("stop", config.container_name))

    def fake_list_local_models(*, base_url: str, request_timeout: float) -> dict:
        if model_pulled:
            return {"models": [{"model": "qwen2.5:7b"}]}
        return {"models": []}

    def fake_pull_model(*, base_url: str, model_name: str) -> None:
        nonlocal model_pulled
        model_pulled = True

    monkeypatch.setattr(ollama_service, "_is_ollama_ready", fake_ready)
    monkeypatch.setattr(ollama_service, "_docker_socket_available", lambda socket_path: True)
    monkeypatch.setattr(ollama_service, "_start_ollama_with_docker_api", fake_start)
    monkeypatch.setattr(ollama_service, "_stop_ollama_with_docker_api", fake_stop)
    monkeypatch.setattr(ollama_service, "_list_local_models", fake_list_local_models)
    monkeypatch.setattr(ollama_service, "_pull_model", fake_pull_model)
    monkeypatch.setattr(ollama_service.asyncio, "to_thread", fake_to_thread)

    async def run_context() -> None:
        async with ollama_service.managed_ollama_service(enabled=True):
            pass

    import asyncio

    asyncio.run(run_context())

    assert events == [
        ("start", "fred-ollama", "ollama/ollama:latest", "ollama_ollama-data"),
        ("stop", "fred-ollama"),
    ]
    assert model_pulled is True


def test_managed_ollama_service_does_nothing_when_disabled(monkeypatch) -> None:
    commands = []

    async def run_context() -> None:
        async with ollama_service.managed_ollama_service(
            enabled=False,
            runner=lambda command, **kwargs: commands.append(command),
        ):
            pass

    import asyncio

    asyncio.run(run_context())

    assert commands == []


def test_resolve_ollama_compose_file_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_COMPOSE_FILE", "none")

    assert ollama_service.resolve_ollama_service_config().compose_file is None


def test_model_detection_accepts_name_or_model() -> None:
    payload = {"models": [{"name": "other"}, {"model": "qwen2.5:7b"}]}

    assert ollama_service._model_is_present(payload, "qwen2.5:7b")


def test_docker_api_payload_requests_nvidia_gpu(monkeypatch) -> None:
    monkeypatch.setenv("CONVERSATION_AI_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("CONVERSATION_AI_BASE_URL", "http://host.docker.internal:11434/v1")
    monkeypatch.setenv("OLLAMA_ENABLE_GPU", "true")

    config = ollama_service.resolve_ollama_service_config()
    payload = ollama_service._build_ollama_container_create_payload(config)

    assert payload["HostConfig"]["DeviceRequests"] == [
        {
            "Driver": "nvidia",
            "Count": -1,
            "Capabilities": [["gpu"]],
        }
    ]


def test_docker_api_payload_can_disable_gpu(monkeypatch) -> None:
    monkeypatch.setenv("CONVERSATION_AI_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("CONVERSATION_AI_BASE_URL", "http://host.docker.internal:11434/v1")
    monkeypatch.setenv("OLLAMA_ENABLE_GPU", "false")

    config = ollama_service.resolve_ollama_service_config()
    payload = ollama_service._build_ollama_container_create_payload(config)

    assert "DeviceRequests" not in payload["HostConfig"]
