"""pcscd domain lock unit tests (B32, 2026-10-19).

Reader/reader coexist, reader/disturbance mutual exclusion, release
semantics — pure flock logic against a tmp_path lock file, journaling
stubbed out (these tests must not write the real bench journal).
"""

import pytest

from tollgate_lab.hardware import pcscd_domain


@pytest.fixture(autouse=True)
def _no_journal(monkeypatch):
    monkeypatch.setattr(pcscd_domain, "bench_event", lambda *a, **k: None)


def test_readers_coexist(tmp_path):
    p = tmp_path / "domain.lock"
    r1 = pcscd_domain.acquire_pcscd_reader(project="t1", path=p)
    r2 = pcscd_domain.acquire_pcscd_reader(project="t2", path=p)
    r1.release()
    r2.release()


def test_disturbance_blocked_by_reader(tmp_path):
    p = tmp_path / "domain.lock"
    r = pcscd_domain.acquire_pcscd_reader(project="t", path=p)
    with pytest.raises(pcscd_domain.PcscdDomainHeldError):
        pcscd_domain.acquire_pcscd_disturbance(project="t", timeout_s=0.0, path=p)
    r.release()


def test_reader_blocked_by_disturbance(tmp_path):
    p = tmp_path / "domain.lock"
    d = pcscd_domain.acquire_pcscd_disturbance(project="t", reason="flash", path=p)
    with pytest.raises(pcscd_domain.PcscdDomainHeldError):
        pcscd_domain.acquire_pcscd_reader(project="t", timeout_s=0.0, path=p)
    d.release()


def test_disturbance_blocked_by_disturbance(tmp_path):
    p = tmp_path / "domain.lock"
    d = pcscd_domain.acquire_pcscd_disturbance(project="t1", path=p)
    with pytest.raises(pcscd_domain.PcscdDomainHeldError):
        pcscd_domain.acquire_pcscd_disturbance(project="t2", timeout_s=0.0, path=p)
    d.release()


def test_release_lets_disturbance_through(tmp_path):
    p = tmp_path / "domain.lock"
    r = pcscd_domain.acquire_pcscd_reader(project="t", path=p)
    r.release()
    d = pcscd_domain.acquire_pcscd_disturbance(project="t", path=p)
    d.release()


def test_disturbance_holder_identified_in_error(tmp_path):
    p = tmp_path / "domain.lock"
    d = pcscd_domain.acquire_pcscd_disturbance(
        project="flash-lane",
        reason="stick flash",
        path=p,
    )
    with pytest.raises(pcscd_domain.PcscdDomainHeldError) as excinfo:
        pcscd_domain.acquire_pcscd_reader(timeout_s=0.0, path=p)
    assert "flash-lane" in str(excinfo.value)
    assert excinfo.value.holder.get("role") == "disturbance"
    d.release()
