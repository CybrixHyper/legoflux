from dataclasses import dataclass
import re

from openai import OpenAI


_ENV_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


@dataclass(frozen=True)
class ModelState:
    profile: str
    model: str
    base_url: str
    client: OpenAI
    max_completion_tokens: int
    timeout_sec: int
    max_retries: int
    retry_backoff_sec: float


class ModelRuntime:
    """Runtime model/profile switcher for OpenAI-compatible backends."""

    def __init__(self, profiles: dict, active: str, defaults: dict | None = None, provider: str = "openai_compatible"):
        if not profiles:
            raise ValueError("model.profiles is empty")
        self._profiles = profiles
        self._defaults = defaults or {}
        self._provider = provider
        self._active_profile = ""
        self._state = None
        self.switch(active)

    @classmethod
    def from_config(cls, cfg):
        model_cfg = cfg.get("model", {}) if isinstance(cfg, dict) else {}
        profiles = model_cfg.get("profiles", {})
        if not isinstance(profiles, dict) or not profiles:
            raise ValueError("model.profiles must be a non-empty mapping")
        active = str(model_cfg.get("active") or next(iter(profiles.keys())))
        provider = str(model_cfg.get("provider", "openai_compatible") or "openai_compatible").strip().lower()
        defaults = {
            "max_completion_tokens": int(model_cfg.get("max_completion_tokens", 4096)),
            "timeout_sec": max(1, int(model_cfg.get("timeout_sec", 120))),
            "max_retries": max(0, int(model_cfg.get("max_retries", 2))),
            "retry_backoff_sec": max(0.0, float(model_cfg.get("retry_backoff_sec", 1.0))),
        }
        return cls(profiles=profiles, active=active, defaults=defaults, provider=provider)

    def list_profiles(self):
        return list(self._profiles.keys())

    def active_profile(self):
        return self._active_profile

    def current(self):
        return self._state

    def switch(self, profile_name: str):
        profile_name = str(profile_name or "").strip()
        if profile_name not in self._profiles:
            raise ValueError(f"unknown model profile: {profile_name}")
        cfg = self._profiles[profile_name]
        if not isinstance(cfg, dict):
            raise ValueError(f"invalid model profile config: {profile_name}")

        if self._provider != "openai_compatible":
            raise ValueError(f"unsupported provider: {self._provider}")

        model = str(cfg.get("name") or "").strip()
        api_key = str(cfg.get("api_key") or "").strip()
        base_url = str(cfg.get("base_url") or "").strip()
        if not model:
            raise ValueError(f"profile '{profile_name}' missing model name")
        if not api_key:
            raise ValueError(f"profile '{profile_name}' missing api_key")
        if not base_url:
            raise ValueError(f"profile '{profile_name}' missing base_url")
        if _ENV_PLACEHOLDER_RE.match(api_key):
            raise ValueError(f"profile '{profile_name}' unresolved env var for api_key: {api_key}")
        if _ENV_PLACEHOLDER_RE.match(base_url):
            raise ValueError(f"profile '{profile_name}' unresolved env var for base_url: {base_url}")

        client = OpenAI(api_key=api_key, base_url=base_url)
        self._state = ModelState(
            profile=profile_name,
            model=model,
            base_url=base_url,
            client=client,
            max_completion_tokens=int(cfg.get("max_completion_tokens", self._defaults.get("max_completion_tokens", 4096))),
            timeout_sec=max(1, int(cfg.get("timeout_sec", self._defaults.get("timeout_sec", 120)))),
            max_retries=max(0, int(cfg.get("max_retries", self._defaults.get("max_retries", 2)))),
            retry_backoff_sec=max(0.0, float(cfg.get("retry_backoff_sec", self._defaults.get("retry_backoff_sec", 1.0)))),
        )
        self._active_profile = profile_name
        return self._state
