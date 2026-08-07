"""xAI (Grok) provider profile."""

from honeyos.runtime import __version__ as _HONEYOS_VERSION
from honeyos.providers import register_provider
from honeyos.providers.base import ProviderProfile

xai = ProviderProfile(
    name="xai",
    aliases=("grok", "x-ai", "x.ai"),
    api_mode="codex_responses",
    env_vars=("XAI_API_KEY",),
    base_url="https://api.x.ai/v1",
    auth_type="api_key",
    default_headers={"User-Agent": f"HoneyOS-Agent/{_HONEYOS_VERSION}"},
)

register_provider(xai)
