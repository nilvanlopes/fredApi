from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
import subprocess
import time
from typing import AsyncIterator, Callable

import httpx

from app.config import (
    get_conversation_ai_base_url,
    get_conversation_ai_model,
    get_ollama_container_name,
    get_ollama_compose_file,
    get_ollama_docker_socket,
    get_ollama_enable_gpu,
    get_ollama_image,
    get_ollama_network,
    get_ollama_manage_service,
    get_ollama_poll_interval_seconds,
    get_ollama_pull_model_when_missing,
    get_ollama_shutdown_when_done,
    get_ollama_startup_timeout_seconds,
    get_ollama_volume,
)


DEFAULT_OLLAMA_API_BASE_URL = "http://localhost:11434/api"
DEFAULT_OLLAMA_OPENAI_BASE_URL = "http://host.docker.internal:11434/v1"
DEFAULT_SHARED_OLLAMA_COMPOSE_FILE = Path("/home/pyu/docker/ollama/docker-compose.yml")
DEFAULT_LOCAL_OLLAMA_COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.ollama.yml"


class OllamaServiceError(RuntimeError):
    pass


async def start_ollama_for_agent() -> bool:
    """Start the ephemeral Ollama and return whether this call owns it."""
    config = resolve_ollama_service_config()
    if not config.manage_service or not config.model_name:
        raise OllamaServiceError("gerenciamento on-demand do Ollama está desabilitado")
    if await asyncio.to_thread(_is_ollama_ready, config.api_base_url):
        if config.pull_model_when_missing:
            await asyncio.to_thread(
                _ensure_model_available,
                model_name=config.model_name,
                base_url=config.api_base_url,
                compose_file=config.compose_file,
                config=config,
                runner=subprocess.run,
            )
        return False

    try:
        if await asyncio.to_thread(_docker_socket_available, config.docker_socket):
            await asyncio.to_thread(_start_ollama_with_docker_api, config)
        elif config.compose_file is not None and config.compose_file.exists():
            await asyncio.to_thread(
                _run_compose,
                ["up", "-d", "ollama"],
                compose_file=config.compose_file,
                runner=subprocess.run,
            )
        else:
            raise OllamaServiceError("nenhum método de inicialização do Ollama está disponível")
        await asyncio.to_thread(
            _wait_until_ready,
            base_url=config.api_base_url,
            timeout_seconds=config.startup_timeout_seconds,
            poll_interval_seconds=config.poll_interval_seconds,
            sleeper=time.sleep,
        )
        if config.pull_model_when_missing:
            await asyncio.to_thread(
                _ensure_model_available,
                model_name=config.model_name,
                base_url=config.api_base_url,
                compose_file=config.compose_file,
                config=config,
                runner=subprocess.run,
            )
        return True
    except Exception:
        await stop_ollama_after_agent(True)
        raise


async def stop_ollama_after_agent(started_by_us: bool) -> None:
    if not started_by_us:
        return
    config = resolve_ollama_service_config()
    if await asyncio.to_thread(_docker_socket_available, config.docker_socket):
        await asyncio.to_thread(_stop_ollama_with_docker_api, config)
    elif config.compose_file is not None:
        await asyncio.to_thread(
            _run_compose,
            ["down"],
            compose_file=config.compose_file,
            runner=subprocess.run,
        )


@dataclass(frozen=True, slots=True)
class OllamaServiceConfig:
    api_base_url: str
    model_name: str
    compose_file: Path | None
    docker_socket: Path
    container_name: str
    image: str
    volume: str
    network: str
    manage_service: bool
    shutdown_when_done: bool
    pull_model_when_missing: bool
    enable_gpu: bool
    startup_timeout_seconds: float
    poll_interval_seconds: float


def resolve_ollama_service_config() -> OllamaServiceConfig:
    return OllamaServiceConfig(
        api_base_url=_resolve_ollama_api_base_url(),
        model_name=get_conversation_ai_model(),
        compose_file=_resolve_compose_file(),
        docker_socket=Path(get_ollama_docker_socket()),
        container_name=get_ollama_container_name(),
        image=get_ollama_image(),
        volume=get_ollama_volume(),
        network=get_ollama_network(),
        manage_service=get_ollama_manage_service(),
        shutdown_when_done=get_ollama_shutdown_when_done(),
        pull_model_when_missing=get_ollama_pull_model_when_missing(),
        enable_gpu=get_ollama_enable_gpu(),
        startup_timeout_seconds=get_ollama_startup_timeout_seconds(),
        poll_interval_seconds=get_ollama_poll_interval_seconds(),
    )


@asynccontextmanager
async def managed_ollama_service(
    *,
    enabled: bool,
    runner: Callable[..., object] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
) -> AsyncIterator[None]:
    if not enabled:
        yield
        return

    config = resolve_ollama_service_config()
    if not config.manage_service:
        yield
        return
    if not config.model_name:
        yield
        return

    if await asyncio.to_thread(_is_ollama_ready, config.api_base_url):
        if config.pull_model_when_missing:
            await asyncio.to_thread(
                _ensure_model_available,
                model_name=config.model_name,
                base_url=config.api_base_url,
                compose_file=config.compose_file,
                config=config,
                runner=runner,
            )
        yield
        return

    started_by_us = False
    try:
        if await asyncio.to_thread(_docker_socket_available, config.docker_socket):
            await asyncio.to_thread(_start_ollama_with_docker_api, config)
        else:
            if config.compose_file is None:
                raise OllamaServiceError(
                    "Ollama nao esta disponivel e nenhum docker-compose foi configurado."
                )
            if not config.compose_file.exists():
                raise OllamaServiceError(
                    f"docker-compose do Ollama nao encontrado: {config.compose_file}"
                )
            await asyncio.to_thread(
                _run_compose,
                ["up", "-d", "ollama"],
                compose_file=config.compose_file,
                runner=runner,
            )
        started_by_us = True
        await asyncio.to_thread(
            _wait_until_ready,
            base_url=config.api_base_url,
            timeout_seconds=config.startup_timeout_seconds,
            poll_interval_seconds=config.poll_interval_seconds,
            sleeper=sleeper,
        )
        if config.pull_model_when_missing:
            await asyncio.to_thread(
                _ensure_model_available,
                model_name=config.model_name,
                base_url=config.api_base_url,
                compose_file=config.compose_file,
                config=config,
                runner=runner,
            )
        yield
    finally:
        if started_by_us and config.shutdown_when_done:
            if await asyncio.to_thread(_docker_socket_available, config.docker_socket):
                await asyncio.to_thread(_stop_ollama_with_docker_api, config)
            elif config.compose_file is not None:
                await asyncio.to_thread(
                    _run_compose,
                    ["down"],
                    compose_file=config.compose_file,
                    runner=runner,
                )


def _resolve_ollama_api_base_url() -> str:
    ai_base_url = get_conversation_ai_base_url()
    if not ai_base_url:
        return DEFAULT_OLLAMA_API_BASE_URL
    return ai_base_url.removesuffix("/v1").removesuffix("/") + "/api"


def _resolve_compose_file() -> Path | None:
    compose_file = get_ollama_compose_file()
    if compose_file is None:
        return None
    if compose_file:
        return Path(compose_file).expanduser()
    if DEFAULT_SHARED_OLLAMA_COMPOSE_FILE.exists():
        return DEFAULT_SHARED_OLLAMA_COMPOSE_FILE
    return DEFAULT_LOCAL_OLLAMA_COMPOSE_FILE


def _is_ollama_ready(base_url: str) -> bool:
    try:
        _list_local_models(base_url=base_url, request_timeout=5.0)
        return True
    except OllamaServiceError:
        return False


def _wait_until_ready(
    *,
    base_url: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    sleeper: Callable[[float], None],
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            _list_local_models(base_url=base_url, request_timeout=5.0)
            return
        except OllamaServiceError as exc:
            last_error = str(exc)
            sleeper(poll_interval_seconds)
    raise OllamaServiceError(
        f"Ollama nao ficou pronto em {timeout_seconds:.0f}s. Ultimo erro: {last_error}"
    )


def _ensure_model_available(
    *,
    model_name: str,
    base_url: str,
    compose_file: Path | None,
    config: OllamaServiceConfig,
    runner: Callable[..., object],
) -> None:
    models_payload = _list_local_models(base_url=base_url, request_timeout=15.0)
    if _model_is_present(models_payload, model_name):
        return
    _pull_model(base_url=base_url, model_name=model_name)
    models_payload = _list_local_models(base_url=base_url, request_timeout=15.0)
    if _model_is_present(models_payload, model_name):
        return
    if _docker_socket_available(config.docker_socket):
        raise OllamaServiceError(f"modelo ausente no Ollama apos pull: {model_name}")
    if compose_file is None:
        raise OllamaServiceError(f"modelo ausente no Ollama: {model_name}")
    _run_compose(
        ["exec", "-T", "ollama", "ollama", "pull", model_name],
        compose_file=compose_file,
        runner=runner,
    )


def _list_local_models(*, base_url: str, request_timeout: float) -> dict:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/tags", timeout=request_timeout)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OllamaServiceError(f"falha ao acessar Ollama: {exc}") from exc


def _pull_model(*, base_url: str, model_name: str) -> None:
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/pull",
            json={"name": model_name, "stream": False},
            timeout=900.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise OllamaServiceError(f"falha ao baixar modelo Ollama {model_name}: {exc}") from exc


def _model_is_present(models_payload: dict, model_name: str) -> bool:
    models = models_payload.get("models", [])
    if not isinstance(models, list):
        return False
    target = model_name.strip().lower()
    for item in models:
        if not isinstance(item, dict):
            continue
        names = [item.get("name"), item.get("model"), item.get("digest")]
        if any(isinstance(name, str) and name.strip().lower() == target for name in names):
            return True
    return False


def _run_compose(
    args: list[str],
    *,
    compose_file: Path,
    runner: Callable[..., object],
) -> None:
    completed = runner(
        ["docker", "compose", "-f", str(compose_file), *args],
        cwd=compose_file.parent,
        stdout=None,
        stderr=None,
        timeout=900,
    )
    if getattr(completed, "returncode", 0) != 0:
        raise OllamaServiceError(
            f"falha ao executar docker compose {' '.join(args)} para Ollama"
        )


def _docker_socket_available(socket_path: Path) -> bool:
    return socket_path.exists()


def _start_ollama_with_docker_api(config: OllamaServiceConfig) -> None:
    existing = _docker_request(config, "GET", f"/containers/{config.container_name}/json")
    if existing.status_code == 404:
        image_name, image_tag = _split_image_reference(config.image)
        _docker_request(
            config,
            "POST",
            "/images/create",
            params={"fromImage": image_name, "tag": image_tag},
            expected_statuses={200},
            timeout=900.0,
        )
        create_response = _docker_request(
            config,
            "POST",
            "/containers/create",
            params={"name": config.container_name},
            json=_build_ollama_container_create_payload(config),
            expected_statuses={201},
        )
        container_id = create_response.json()["Id"]
        existing_data = None
    else:
        _ensure_docker_success(existing, expected_statuses={200})
        container_id = existing.json()["Id"]
        existing_data = existing.json()

    _docker_request(
        config,
        "POST",
        f"/containers/{container_id}/start",
        expected_statuses={204, 304},
    )
    _ensure_ollama_network(config, container_id, existing=existing_data)


def _ensure_ollama_network(
    config: OllamaServiceConfig,
    container_id: str,
    existing: dict | None,
) -> None:
    networks = (existing or {}).get("NetworkSettings", {}).get("Networks", {})
    if config.network in networks:
        return
    _docker_request(
        config,
        "POST",
        f"/networks/{config.network}/connect",
        json={"Container": container_id, "EndpointConfig": {"Aliases": [config.container_name]}},
        expected_statuses={200},
    )


def _build_ollama_container_create_payload(config: OllamaServiceConfig) -> dict:
    host_config = {
        "Binds": [f"{config.volume}:/root/.ollama"],
        "PortBindings": {"11434/tcp": [{"HostPort": "11434"}]},
        "RestartPolicy": {"Name": "unless-stopped"},
    }
    if config.enable_gpu:
        host_config["DeviceRequests"] = [
            {
                "Driver": "nvidia",
                "Count": -1,
                "Capabilities": [["gpu"]],
            }
        ]
    return {
        "Image": config.image,
        "ExposedPorts": {"11434/tcp": {}},
        "HostConfig": host_config,
    }


def _stop_ollama_with_docker_api(config: OllamaServiceConfig) -> None:
    existing = _docker_request(config, "GET", f"/containers/{config.container_name}/json")
    if existing.status_code == 404:
        return
    _ensure_docker_success(existing, expected_statuses={200})
    container_id = existing.json()["Id"]
    _docker_request(
        config,
        "POST",
        f"/containers/{container_id}/stop",
        expected_statuses={204, 304},
        timeout=30.0,
    )
    _docker_request(
        config,
        "DELETE",
        f"/containers/{container_id}",
        params={"v": "false"},
        expected_statuses={204, 404},
    )


def _split_image_reference(image: str) -> tuple[str, str]:
    last_component = image.rsplit("/", 1)[-1]
    if ":" not in last_component:
        return image, "latest"
    image_name, image_tag = image.rsplit(":", 1)
    return image_name, image_tag or "latest"


def _docker_request(
    config: OllamaServiceConfig,
    method: str,
    path: str,
    *,
    expected_statuses: set[int] | None = None,
    timeout: float = 60.0,
    **kwargs,
) -> httpx.Response:
    url = f"http://docker{path}"
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds=str(config.docker_socket))) as client:
            response = client.request(method, url, timeout=timeout, **kwargs)
    except httpx.HTTPError as exc:
        raise OllamaServiceError(f"falha ao acessar Docker API: {exc}") from exc
    if expected_statuses is not None:
        _ensure_docker_success(response, expected_statuses=expected_statuses)
    return response


def _ensure_docker_success(
    response: httpx.Response,
    *,
    expected_statuses: set[int],
) -> None:
    if response.status_code in expected_statuses:
        return
    raise OllamaServiceError(
        f"Docker API retornou HTTP {response.status_code}: {response.text[:500]}"
    )
