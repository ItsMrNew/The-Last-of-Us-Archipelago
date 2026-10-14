"""Standalone research tools and the Archipelago world share one catalog."""

if __name__.startswith("worlds."):
    from .world import TLOUWorld
