from fastapi.testclient import TestClient

from r1svc import bindsvc


def test_get_user_info_json():
    c = TestClient(bindsvc.app(log_path=None))
    r = c.post("/getUserInfo", json={"udid": "abcd"})
    assert r.status_code == 200
    assert r.json() == {"status": "0"}


def test_catch_all_json():
    c = TestClient(bindsvc.app(log_path=None))
    r = c.get("/some/path?q=1")
    assert r.status_code == 200
    assert r.json() == {"status": "0", "code": 0, "message": "ok"}


def test_favicon_204():
    c = TestClient(bindsvc.app(log_path=None))
    r = c.get("/favicon.ico")
    assert r.status_code == 204


def test_access_log_written(tmp_path):
    p = tmp_path / "bind_access.log"
    c = TestClient(bindsvc.app(log_path=p))
    c.post("/getUserInfo", json={"x": 1})
    s = p.read_text(encoding="utf-8")
    assert "POST /getUserInfo" in s and '"x":1' in s
