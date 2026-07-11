from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ES_", extra="ignore")

    database_url: str = "postgresql+psycopg://es:es_dev_only@localhost:55432/es"

    host: str = "127.0.0.1"
    port: int = 8731

    # Ordered fallback chain for the LLM Router. Each entry is a litellm
    # model string; the router tries them in order until one succeeds.
    # Empty by default — no key is assumed to be configured yet.
    coding_models: list[str] = []
    fast_models: list[str] = []

    # Set via ES_ANTHROPIC_API_KEY / ES_OPENAI_API_KEY / ollama base url etc,
    # or leave to the underlying provider SDKs' own env vars
    # (ANTHROPIC_API_KEY, OPENAI_API_KEY) which litellm reads directly.
    ollama_base_url: str = "http://localhost:11434"

    # Coding Agent (Phase 1)
    semgrep_docker_image: str = "semgrep/semgrep:latest"
    semgrep_timeout_seconds: int = 300
    test_run_timeout_seconds: int = 600
    fix_max_findings_per_patch: int = 5

    # Pentest Agent / Tool Orchestrator (Phase 2)
    httpx_docker_image: str = "projectdiscovery/httpx:latest"
    nmap_docker_image: str = "instrumentisto/nmap:latest"
    tool_timeout_seconds: int = 180

    # Every target must reach `verified` status via api/scope.py before any
    # active-scan tool call — see docs/SECURITY_AND_AUTHORIZATION.md.
    scope_verification_ttl_days: int = 30

    # Docker Desktop (Windows/Mac) can't reach the host via localhost/127.0.0.1
    # from inside a container; it exposes the host under this DNS name instead.
    # On Linux Docker (no Docker Desktop), set this to the docker0 gateway IP
    # or run with --network=host and set it to "localhost".
    container_host_alias: str = "host.docker.internal"


settings = Settings()
