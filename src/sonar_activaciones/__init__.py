"""CPU-only public SDK. Qt and model frameworks are never imported here."""

from .contracts import MonitorConfig, Observation, ProbeDescriptor

__version__ = "0.2.0"
__all__ = ["MonitorConfig", "Observation", "ProbeDescriptor", "open_monitor"]


def open_monitor(probes, config=None):
    from .session import open_monitor as launch

    return launch(probes, config)

