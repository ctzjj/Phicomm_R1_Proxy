package asr

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// isFinalRequest reports whether this is the "utterance finished" request:
// Content-Length 0 plus the TP (token params) header.
func isFinalRequest(hdr []byte) bool {
	cl, ok := contentLength(hdr)
	if !ok || cl != 0 {
		return false
	}
	return bytes.Contains(hdr, []byte("\r\nTP:")) || bytes.HasPrefix(hdr, []byte("TP:"))
}

var nluClient = &http.Client{Timeout: 12 * time.Second}

// postNLU sends one utterance (Ogg/Opus) to the user's NLU service.
func postNLU(snap Snapshot, sid string, ogg []byte) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, snap.NLUURL, bytes.NewReader(ogg))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "audio/ogg")
	req.Header.Set("X-R1-SID", sid)
	req.Header.Set("X-R1-Sample-Rate", "16000")
	req.Header.Set("X-R1-Channels", "1")
	if key := strings.TrimSpace(snap.NLUKey); key != "" {
		h := snap.NLUKeyHeader
		if h == "" {
			h = "Authorization"
		}
		if strings.EqualFold(h, "Authorization") && !strings.HasPrefix(strings.ToLower(key), "bearer ") {
			key = "Bearer " + key
		}
		req.Header.Set(h, key)
	}
	resp, err := nluClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("nlu: http %d", resp.StatusCode)
	}
	if len(bytes.TrimSpace(body)) == 0 {
		return nil, fmt.Errorf("nlu: empty response")
	}
	return body, nil
}

// nluResponse wraps the NLU service answer into the response the speaker
// expects. A JSON object (containing "code") is returned verbatim; plain text
// becomes an ANSWER intent.
func nluResponse(sid string, body []byte) []byte {
	trimmed := bytes.TrimSpace(body)
	var payload []byte
	if len(trimmed) > 0 && trimmed[0] == '{' {
		payload = trimmed
	} else {
		text := strings.TrimSpace(string(trimmed))
		obj := map[string]any{
			"code":          "ANSWER",
			"general":       map[string]any{"text": text, "type": "T"},
			"asr_recongize": text,
		}
		payload, _ = json.Marshal(obj)
	}
	var b strings.Builder
	b.WriteString("HTTP/1.1 200 OK\r\n")
	b.WriteString("CT: W510\r\n")
	b.WriteString("RS: GeLdJ\r\n")
	b.WriteString("PN: ry\r\n")
	if sid != "" {
		fmt.Fprintf(&b, "SID: %s\r\n", sid)
	}
	b.WriteString("Content-Type: application/json\r\n")
	fmt.Fprintf(&b, "Content-Length: %d\r\n", len(payload))
	b.WriteString("Connection: keep-alive\r\n\r\n")
	b.Write(payload)
	return []byte(b.String())
}
