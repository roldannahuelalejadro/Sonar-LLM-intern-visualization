"""Synthetic CPU example. Replace values with your own real activation vector."""
import time
import numpy as np
from sonar_activaciones import MonitorConfig, ProbeDescriptor, open_monitor


def main():
    probe = ProbeDescriptor("manual", "EJEMPLO SINTETICO", "manual-example", "cpu_vector",
                            64, "vector completo", "synthetic/manual-v1", metadata={"synthetic": True})
    with open_monitor([probe], MonitorConfig(capture_hz=30)) as monitor:
        for step in range(1800):
            if monitor.status()["state"] != "connected":
                print("Ventana cerrada; el productor sigue su propia ejecucion.")
                break
            if monitor.capture_allowed("manual"):
                values = np.sin(np.arange(64) / 7 + step / 12)
                monitor.publish("manual", values, {"stream_id": "example", "processed_position": step,
                                                    "stage": "synthetic"})
            time.sleep(1/30)
        print(monitor.status())


if __name__ == "__main__":
    main()
