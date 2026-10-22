package asr

import (
	"bufio"
	"bytes"
	"strings"
	"testing"
)

func TestReadMessageChunked(t *testing.T) {
	const raw = "POST /trafficRouter/cs HTTP/1.1\r\n" +
		"Host: asrv3.hivoice.cn\r\n" +
		"Transfer-Encoding: chunked\r\n" +
		"\r\n" +
		"5\r\nHELLO\r\n" +
		"6\r\n WORLD\r\n" +
		"0\r\n\r\n"
	msg, err := readMessage(bufio.NewReader(strings.NewReader(raw)), 1<<20)
	if err != nil {
		t.Fatalf("readMessage: %v", err)
	}
	if got := string(msg.body); got != "HELLO WORLD" {
		t.Fatalf("body = %q, want %q", got, "HELLO WORLD")
	}
	if string(msg.raw) != raw {
		t.Fatalf("raw was modified")
	}
	hdr, body := splitHTTP([]byte(raw))
	if !bytes.HasSuffix(hdr, []byte("\r\n\r\n")) {
		t.Fatalf("bad header split: %q", hdr)
	}
	if string(body) != "HELLO WORLD" {
		t.Fatalf("splitHTTP body = %q", body)
	}
}

func TestReadMessageContentLength(t *testing.T) {
	const raw = "POST /trafficRouter/sa HTTP/1.1\r\nContent-Length: 4\r\n\r\nABCD"
	msg, err := readMessage(bufio.NewReader(strings.NewReader(raw)), 1<<20)
	if err != nil {
		t.Fatalf("readMessage: %v", err)
	}
	if string(msg.body) != "ABCD" {
		t.Fatalf("body = %q", msg.body)
	}
}

func TestDechunkPartial(t *testing.T) {
	if got := string(dechunk([]byte("4\r\nAB"))); got != "" {
		t.Fatalf("partial chunk should yield nothing, got %q", got)
	}
}
