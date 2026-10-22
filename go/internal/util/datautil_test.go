package util

import (
	"strings"
	"testing"
)

func TestParseAndBuild(t *testing.T) {
	raw := []byte("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}")
	d, err := Parse(raw)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if d.Body == nil {
		t.Fatal("body not decoded")
	}
	d.Body = map[string]any{"text": "你好", "url": "http://a/b"}
	out := string(d.Build())
	want := `{"text":"你好","url":"http://a/b"}`
	if !strings.HasSuffix(out, want) {
		t.Fatalf("body = %q, want suffix %q", out, want)
	}
	if !strings.Contains(out, "Content-Length: 36\r\n\r\n") {
		t.Fatalf("content-length not rewritten: %q", out)
	}
	if strings.Contains(out, `\/`) {
		t.Fatal("slashes must not be escaped")
	}
}

func TestParseNonJSONPassThrough(t *testing.T) {
	raw := []byte("HTTP/1.1 404 Not Found\r\nContent-Length: 3\r\n\r\nabc")
	d, err := Parse(raw)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if _, ok := d.Body.(string); !ok {
		t.Fatalf("expected string body, got %T", d.Body)
	}
}

func TestGetString(t *testing.T) {
	body := map[string]any{"semantic": map[string]any{"intent": map[string]any{"keyword": "abc"}}}
	if got := GetString(body, "semantic", "intent", "keyword"); got != "abc" {
		t.Fatalf("got %q", got)
	}
	if got := GetString(body, "semantic", "nope"); got != "" {
		t.Fatalf("got %q", got)
	}
}
