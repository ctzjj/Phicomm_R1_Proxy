from r1svc import web_search
from r1svc.asr_engine import qa_llm

BING_HTML = """<ol id="b_results">
<li class="b_algo"><h2><a href="https://a.example/1">上海天气预报</a></h2>
<p class="b_lineclamp2">今天上海多云转晴，18到25度。</p></li>
<li class="b_algo"><h2><a href="https://b.example/2">上海今日天气实况</a></h2>
<p>空气湿度 60%，东南风 3 级。</p></li>
</ol>"""


def test_bing_parse(monkeypatch):
    monkeypatch.setattr(web_search, "_fetch", lambda url, timeout: BING_HTML)
    res = web_search.search("上海天气")
    assert len(res) == 2
    assert res[0]["title"] == "上海天气预报"
    assert "18到25度" in res[0]["snippet"]
    assert res[1]["url"] == "https://b.example/2"


def _tool_call(name, args="{}"):
    return {"id": "c1", "type": "function",
            "function": {"name": name, "arguments": args}}


def test_llm_tool_flow(monkeypatch):
    calls = []
    searched = []

    def fake_msg(messages, tools=None, temp=0.7, tool_choice="auto", seed=None,
                 max_tokens=120, thinking=False):
        calls.append({"messages": list(messages), "tools": tools,
                      "max_tokens": max_tokens})
        if tools:
            return {"role": "assistant", "content": "",
                    "tool_calls": [_tool_call("web_search",
                                              '{"query":"今天新闻"}')]}
        return {"role": "assistant", "content": "今天新闻不少,比如1966年的今天。"}

    def fake_search(q, *a, **k):
        searched.append(q)
        return [{"title": "今天新闻", "snippet": "大事记", "url": ""}]

    monkeypatch.setattr(qa_llm, "_http_msg", fake_msg)
    monkeypatch.setattr(qa_llm, "_api", "http://x/v1/chat/completions")
    monkeypatch.setattr(qa_llm, "_enabled", True)
    monkeypatch.setattr(qa_llm, "_web_search", True)
    monkeypatch.setattr(qa_llm, "_load_ok", True)
    monkeypatch.setattr(web_search, "search", fake_search)
    qa_llm.clear_history()
    out = qa_llm.answer("今天有什么新闻")
    assert "1966" in out
    assert len(calls) == 2
    assert calls[0]["tools"] and calls[1]["tools"] is None
    assert calls[1]["max_tokens"] > calls[0]["max_tokens"]
    assert searched == ["今天新闻"]
    last = calls[1]["messages"][-1]
    assert last["role"] == "tool" and "大事记" in last["content"]
    qa_llm.set_api("")
    qa_llm.set_web_search(False)
    qa_llm.clear_history()


def test_llm_direct_answer_no_search(monkeypatch):
    calls = []

    def fake_msg(messages, tools=None, temp=0.7, tool_choice="auto", seed=None,
                 max_tokens=120, thinking=False):
        calls.append((list(messages), tools))
        return {"role": "assistant", "content": "从前有只猫,它不讲笑话。"}

    monkeypatch.setattr(qa_llm, "_http_msg", fake_msg)
    monkeypatch.setattr(qa_llm, "_api", "http://x/v1/chat/completions")
    monkeypatch.setattr(qa_llm, "_enabled", True)
    monkeypatch.setattr(qa_llm, "_web_search", True)
    monkeypatch.setattr(qa_llm, "_load_ok", True)
    monkeypatch.setattr(web_search, "search",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not search")))
    qa_llm.clear_history()
    out = qa_llm.answer("给我讲个笑话")
    assert "猫" in out
    assert len(calls) == 1          # 不调工具就一轮出答案
    assert calls[0][1]              # 但工具列表有给到模型自选


def test_answer_disabled_or_failed_returns_fallback(monkeypatch):
    # 开关关:播服务异常提示
    monkeypatch.setattr(qa_llm, "_enabled", False)
    qa_llm.clear_history()
    assert qa_llm.answer("给我讲个笑话") == qa_llm.CHAT_UNAVAILABLE
    # 内部模型加载失败:同样播服务异常提示
    monkeypatch.setattr(qa_llm, "_enabled", True)
    monkeypatch.setattr(qa_llm, "_api", "")
    monkeypatch.setattr(qa_llm, "_load_ok", False)
    monkeypatch.setattr(qa_llm, "_load", lambda log=None: False)
    assert qa_llm.answer("给我讲个笑话") == qa_llm.CHAT_UNAVAILABLE
    qa_llm.set_api("")
    qa_llm.set_web_search(False)
    qa_llm.clear_history()


def test_run_tool_news_and_history(monkeypatch):
    monkeypatch.setattr(web_search, "_news",
                        lambda n, t: [{"title": "头条", "snippet": "",
                                       "url": "", "date": "10月27日 12:00"}])
    assert "头条" in qa_llm._run_tool("news", {})

    monkeypatch.setattr(web_search, "search",
                        lambda q, *a, **k: [{"title": "历史上的今天",
                                             "snippet": "1927年10月27日 井冈山",
                                             "url": ""}])
    assert "1927" in qa_llm._run_tool("history_today", {})


def test_history_lines_extract():
    txt = web_search.history_lines([{
        "title": "历史上的今天",
        "snippet": "♦ 1927年10月27日 中共创建井冈山根据地。2026年10月3日 查询历史事件"}])
    assert "1927年10月27日" in txt
    assert "查询" not in txt


def test_format_truncates():
    txt = web_search.format_results([{"title": "t", "snippet": "s" * 1000}],
                                    max_chars=50)
    assert len(txt) == 50
