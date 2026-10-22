// Package util implements the HTTP message handling used by asr_proxy:
// parse a raw HTTP response into header + JSON body, let the caller replace
// the body, then rebuild the message with a corrected Content-Length.
package util

import (
	"bytes"
	"encoding/json"
	"errors"
	"regexp"
	"strings"
)

// Data holds one HTTP message.
type Data struct {
	// Header is everything up to and including the blank line, e.g.
	// "HTTP/1.1 200 OK\r\nContent-Length: 12\r\n\r\n".
	Header string
	// Body is the JSON-decoded body (map[string]any for JSON objects,
	// nil when the body is empty or not JSON).
	Body any
	// Origin is the raw message as received.
	Origin []byte
}

var contentLengthRe = regexp.MustCompile(`(?i)Content-Length: [0-9]+(\r\n\r\n)`)

// Parse splits a raw HTTP message on the first "\r\n\r\n" and decodes the
// body as JSON. A body that is not valid JSON is kept as a string so that
// it can still be passed through unchanged.
func Parse(raw []byte) (*Data, error) {
	idx := bytes.Index(raw, []byte("\r\n\r\n"))
	if idx < 0 {
		return nil, errors.New("util: no header/body separator")
	}
	hdrEnd := idx + 4
	d := &Data{
		Header: string(raw[:hdrEnd]),
		Origin: raw,
	}
	body := raw[hdrEnd:]
	if len(bytes.TrimSpace(body)) == 0 {
		return d, nil
	}
	var v any
	if err := json.Unmarshal(body, &v); err != nil {
		d.Body = string(body)
		return d, nil
	}
	d.Body = v
	return d, nil
}

// Build re-encodes Body as compact JSON (no HTML escaping, no escaped
// slashes) and rewrites the Content-Length header, mirroring the PHP
// DataUtil::build() behaviour.
func (d *Data) Build() []byte {
	if d.Body == nil {
		return []byte(d.Header)
	}
	body := MarshalBody(d.Body)
	hdr := d.Header
	if contentLengthRe.MatchString(hdr) {
		hdr = contentLengthRe.ReplaceAllString(hdr, "Content-Length: "+itoa(len(body))+"$1")
	}
	return append([]byte(hdr), body...)
}

// MarshalBody encodes v as compact JSON without HTML escaping, matching
// PHP's json_encode($v, JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE).
func MarshalBody(v any) []byte {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil
	}
	return bytes.TrimRight(buf.Bytes(), "\n")
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	return string(b[i:])
}

// GetString reads a nested string field from a map body, e.g.
// GetString(body, "semantic", "intent", "keyword").
func GetString(body any, path ...string) string {
	cur := body
	for _, p := range path {
		m, ok := cur.(map[string]any)
		if !ok {
			return ""
		}
		cur = m[p]
	}
	s, _ := cur.(string)
	return s
}

// HeaderValue returns the value of a header (case-insensitive).
func (d *Data) HeaderValue(name string) string {
	for _, line := range strings.Split(d.Header, "\r\n") {
		if i := strings.IndexByte(line, ':'); i > 0 {
			if strings.EqualFold(strings.TrimSpace(line[:i]), name) {
				return strings.TrimSpace(line[i+1:])
			}
		}
	}
	return ""
}
