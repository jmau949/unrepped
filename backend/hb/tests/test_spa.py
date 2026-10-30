import pytest

from hb.main import _dist_file


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html></html>")
    (root / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("do not serve")  # sibling, outside dist
    return root


def test_serves_a_file_inside_dist(dist):
    assert _dist_file(dist, "assets/app.js") == (dist / "assets" / "app.js").resolve()


@pytest.mark.parametrize("path", ["", "listings/123", "missing.js"])
def test_no_file_for_root_deep_links_and_missing_files(dist, path):
    assert _dist_file(dist, path) is None


@pytest.mark.parametrize("path", ["../secret.txt", "assets/../../secret.txt"])
def test_dot_dot_never_escapes_dist(dist, path):
    assert _dist_file(dist, path) is None


def test_absolute_path_never_escapes_dist(dist, tmp_path):
    assert _dist_file(dist, str(tmp_path / "secret.txt")) is None


def test_embedded_nul_is_rejected_not_raised(dist):
    assert _dist_file(dist, "a\x00b") is None


def test_root_explains_itself_before_the_first_build():
    """A checkout before its first `make build` (CI's backend job, a fresh clone
    whose `make start` is still loading data) answers / with the fix, not a bare
    404; once built, / is the SPA shell."""
    from fastapi.testclient import TestClient

    from hb import main

    resp = TestClient(main.app).get("/")
    if main._DIST.is_dir():
        assert resp.status_code == 200 and 'id="root"' in resp.text
    else:
        assert resp.status_code == 503 and "make build" in resp.text
