"""Exercise the public spawn entrypoint, with a real local window."""
import time
import numpy as np
from sonar_activaciones import ProbeDescriptor, open_monitor


def main():
    p = ProbeDescriptor("smoke", "SMOKE SINTETICO", "sdk-test", "cpu", 19, "all", "synthetic/sdk-v1",
                        metadata={"synthetic": True})
    with open_monitor([p]) as session:
        for i in range(30):
            assert session.publish("smoke", np.sin(np.arange(19)+i*.1)) in ("accepted", "dropped")
            time.sleep(.02)
        time.sleep(.2)
        status = session.status()
        assert status["received"] > 0 and status["drawn"] > 0, status
        print(status)
    assert session.status()["state"] == "closed"
    print("Public SDK spawn, reception, painting and close: OK")


if __name__ == "__main__":
    main()
