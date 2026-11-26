from .base import CatalogProvider
from .enamine import EnamineProvider

_PROVIDERS: dict[str, CatalogProvider] = {"enamine": EnamineProvider()}


def register(provider: CatalogProvider) -> None:
    _PROVIDERS[provider.name] = provider


def get(name: str) -> CatalogProvider:
    try:
        return _PROVIDERS[name.lower()]
    except KeyError as exc:
        raise ValueError(f"Unknown provider {name!r}; available: {sorted(_PROVIDERS)}") from exc
