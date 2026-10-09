from dataclasses import replace
import numpy as np
import pytest
from sonar_activaciones import MonitorConfig, Observation
from sonar_activaciones.contracts import MIB
from sonar_activaciones.app.state import ViewerState
from sonar_activaciones.processing.memory import plan_memory
from sonar_activaciones.processing.projection import component_basis
from .test_core import probe


def small_config(**kw):
    return MonitorConfig(data_budget_bytes=MIB, queue_capacity=1, max_sample_bytes=32768,
                         work_bytes=0, recent_fraction=.2, **kw)


@pytest.mark.parametrize("d", [70, 4096, 5120])
@pytest.mark.parametrize("budget", [MIB, 64*MIB])
def test_global_budget(d, budget):
    probes = [probe(dimension=d), probe(probe_id="other", dimension=70)]
    config = replace(small_config(), data_budget_bytes=budget)
    try:
        plan = plan_memory(probes, config)
    except ValueError as exc:
        assert budget == MIB and "minimo calculado" in str(exc)
        return
    assert plan.committed <= budget
    assert abs(plan.recent["p"] - plan.recent["other"]) <= 1
    assert plan.capacities(probes)["p"]["recent_approx"] >= 1


def test_default_and_legacy_are_not_reinterpreted():
    p = probe()
    plan = plan_memory([p], MonitorConfig())
    assert plan.total == 64*MIB and not plan.legacy
    old = plan_memory([p], MonitorConfig(history_bytes=64*MIB))
    assert old.recent["p"] == 64*MIB and old.total > 64*MIB and old.legacy
    with pytest.raises(ValueError, match="minimo"):
        plan_memory([p], MonitorConfig(data_budget_bytes=MIB))


def test_one_mib_admissible_with_explicit_small_transport():
    p = probe(dimension=70)
    config = MonitorConfig(data_budget_bytes=MIB, queue_capacity=1, max_sample_bytes=4096, work_bytes=0)
    state = ViewerState([p], config)
    state.ingest(Observation.create(p, np.ones(70), 0, max_bytes=4096))
    assert state.current().sequence == 0
    assert state.plan.committed <= MIB


def test_two_rings_frozen_reference_and_union():
    p = probe(dimension=4096)
    # Small admitted quotas but room for operation/transport reservations.
    config = replace(small_config(), data_budget_bytes=2*MIB, recent_fraction=.05)
    state = ViewerState([p], config)
    state.install_basis(component_basis(p, [0, 1]))
    for i in range(600):
        state.ingest(Observation.create(p, np.full(p.dimension, i, dtype=np.float32), i))
        if i == 5:
            state.freeze()
            state.set_reference()
    assert state.current().sequence == 5
    assert state.references["p"].sequence == 5
    ring = state.history.rings["p"]
    assert 5 not in ring.frames
    assert state.history.counters["vector_retired_projection_kept"] > 0
    assert state.history.counters["capture_retired"] > 0
    projection_only = next(f for f in ring.frames.values() if f.availability == "projection")
    state.freeze_sequence(projection_only.sequence)
    assert state.current() is None and state.values() is None
    assert state.selection().availability == "projection"
    state.live()
    assert state.current().sequence == 599
    assert state.history.used_bytes <= sum(state.plan.recent.values())+sum(state.plan.projected.values())
    assert len(state.history.events) == 128
    np.testing.assert_array_equal(np.frombuffer(state.selection().projections[state.selected_segment], '<f4'), [599, 599])


def test_base_segments_and_reconfiguration():
    p = probe(dimension=70)
    state = ViewerState([p], replace(small_config(), data_budget_bytes=2*MIB))
    for i in range(100):
        state.ingest(Observation.create(p, np.arange(70, dtype=np.float32)+i, i))
    assert not state.selection().projections
    a, b = component_basis(p, [0, 1]), component_basis(p, [2, 3])
    state.install_basis(a)
    state.process_reprojections(512, 1000)
    state.install_basis(b)
    state.process_reprojections(512, 1000)
    assert set(state.selection().projections) == {a.basis_id, b.basis_id}
    state.freeze()
    state.set_reference()
    with pytest.raises(ValueError, match="congelada"):
        state.retire_segment(a.basis_id)
    config = replace(state.config, data_budget_bytes=3*MIB)
    before = state.history.used_bytes
    state.reconfigure(config)
    assert state.history.used_bytes == before
    assert state.selection().sequence == 99 and state.references["p"].sequence == 99
    state.live()
    state.retire_segment(a.basis_id)
    assert a.basis_id not in state.segments
    assert a.basis_id not in state.selection().projections


def test_pca_rejected_before_pinning():
    p = probe(dimension=70)
    state = ViewerState([p], replace(small_config(), data_budget_bytes=2*MIB))
    for i in range(10):
        state.ingest(Observation.create(p, np.ones(70), i))
    with pytest.raises(ValueError, match="reserva"):
        state.pca_snapshot(10, 2)
    assert state.work.active is None


def test_reconfiguration_cannot_undercharge_existing_transport():
    state = ViewerState([probe()], MonitorConfig())
    before = state.plan
    with pytest.raises(ValueError, match='transporte'):
        state.reconfigure(replace(state.config, queue_capacity=1))
    assert state.plan is before


def test_projection_overflow_is_not_vector_loss():
    from sonar_activaciones.processing.projection import DirectionBasis
    p = probe()
    state = ViewerState([p], MonitorConfig())
    b = DirectionBasis('overflow', p.space_id, ('a',), 'synthetic', np.ones((3,1))*1e30, np.zeros(3), np.ones(3))
    state.install_basis(b)
    state.ingest(Observation.create(p, np.full(3, 1e30), 0))
    assert state.selection().availability == 'vector'
    assert state.history.counters['projection_nonfinite'] == 1


def test_history_ownership_has_no_gc_cycle_and_releases_index_capacity():
    import gc
    import sys
    import weakref
    p = probe()
    state = ViewerState([p], MonitorConfig(history_bytes=8*MIB))
    for i in range(1000):
        state.ingest(Observation.create(p, np.ones(3), i))
    ring = state.history.rings['p']
    old_capacity = sys.getsizeof(ring.frames)
    state.reconfigure(replace(state.config, history_bytes=30000))
    assert sys.getsizeof(ring.frames) < old_capacity/10
    history_ref = weakref.ref(state.history)
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        del ring, state
        assert history_ref() is None
    finally:
        if was_enabled:
            gc.enable()
