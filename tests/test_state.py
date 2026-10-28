from r1svc import state
import json


def test_ring_log_and_seq():
    s = state.State()
    s.log("hello", "world")
    s.log("second")
    rows = s.logs()
    assert rows[-1]["msg"] == "second"
    assert rows[0]["msg"] == "hello world"
    assert rows[-1]["seq"] == 2
    n = s.next_seq()  # one seq consumed per log()
    assert n >= 2


def test_capture_two_session_flow(tmp_path, monkeypatch):
    pkt = b"\x01\x00" + b"P" * 12
    final = b""
    stub = lambda b: [b] if b else []
    s = state.State()
    hdr1 = b"POST /trafficRouter/cs HTTP/1.1\r\nP: abc[SID-A]\r\n\r\n"
    hdr2 = b"POST /trafficRouter/cs HTTP/1.1\r\nP: abc[SID-A]\r\nTP: replay\r\n\r\n"
    s.cap_add(hdr1, pkt, chunk_parse=stub)
    n, ogg = s.cap_finalize("SID-A", ogg_func=lambda pkts: b"|".join(pkts))
    assert n == 1
    assert ogg == pkt  # muxer replaced by stub; correctness lives in test_protocol
    s.cap_add(hdr1, pkt, chunk_parse=stub)
    s.cap_add(hdr2, final, chunk_parse=stub)          # empty body = final: finalize & drop
    n2, ogg2 = s.cap_finalize("SID-A", ogg_func=lambda pkts: b"|".join(pkts))
    assert n2 == 0 and ogg2 is None


def test_capture_three_second_split():
    s = state.State()
    pkt = b"\x01\x00AAAA"
    stub = lambda b: [b] if b else []
    h = b"POST /trafficRouter/cs HTTP/1.1\r\nP: k[S1]\r\n\r\n"
    s.cap_add(h, pkt, chunk_parse=stub)
    # simulate >3s gap
    s._sessions["S1"].at -= 4.0
    s.cap_add(h, pkt, chunk_parse=stub)   # triggers auto-finalize of previous utterance
    assert s._sessions["S1"].seq == 2


def test_dump_writes_compat_files(tmp_path, monkeypatch):
    import time
    s = state.State()
    hdr = b"POST /trafficRouter/cs HTTP/1.1\r\nP: k[x]\r\n\r\n"
    body = b"\x01\x00abcd"
    # 内部重置不依赖 dump_dir 目录扫描,避免误用重复 0001
    monkeypatch.setattr(state, "DUMP_DIR_HINT", tmp_path)
    s.dump("req", tmp_path, 1, hdr, body, extra={"sid": "x"})
    for suffix in (".hdr", ".bin", ".txt"):
        assert (tmp_path / f"0001_req{suffix}").exists()
    idx = (tmp_path / "index.log").read_text(encoding="utf-8")
    assert "#0001 req" in idx and "POST /trafficRouter/cs" in idx
    txt = (tmp_path / "0001_req.txt").read_text(encoding="utf-8")
    assert "first32=" in txt
    data = (tmp_path / "0001_req.bin").read_bytes()
    assert data == body
    hdrraw = (tmp_path / "0001_req.hdr").read_bytes()
    assert hdrraw == hdr
