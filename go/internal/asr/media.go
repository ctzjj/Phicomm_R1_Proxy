package asr

import (
	"bufio"
	"encoding/base64"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// mediaClient fetches the upstream audio; no decompression so Content-Length
// stays meaningful for the speaker.
var mediaClient = &http.Client{
	Timeout: 30 * time.Second,
	Transport: &http.Transport{
		MaxIdleConns:        32,
		MaxIdleConnsPerHost: 8,
		IdleConnTimeout:     60 * time.Second,
		DisableCompression:  true,
	},
}

// isMediaRequest reports whether the intercepted request targets /media.
func isMediaRequest(hdr []byte) bool {
	line := requestLine(hdr)
	if !strings.HasPrefix(line, "GET ") && !strings.HasPrefix(line, "HEAD ") {
		return false
	}
	return strings.Contains(line, " /media?") || strings.Contains(line, " /media ")
}

// serveMedia streams an upstream music url back to the speaker with clean
// headers (no Content-Disposition / x-nos-*, proper Content-Type and
// Content-Length, Range support).
func serveMedia(w io.Writer, msg *message) {
	line := requestLine(msg.hdr)
	if strings.HasPrefix(line, "HEAD ") {
		serveMediaHead(w, msg)
		return
	}

	target, err := mediaTarget(line)
	if err != nil {
		writeStatus(w, 400, "")
		return
	}
	req, err := http.NewRequest(http.MethodGet, target, nil)
	if err != nil {
		writeStatus(w, 400, "")
		return
	}
	if r := headerValue(msg.hdr, "Range"); r != "" {
		req.Header.Set("Range", r)
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36")
	req.Header.Set("Referer", "https://music.163.com/")

	resp, err := mediaClient.Do(req)
	if err != nil {
		writeStatus(w, 502, "")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusPartialContent {
		writeStatus(w, http.StatusBadGateway, "")
		return
	}

	var h strings.Builder
	status := "200 OK"
	if resp.StatusCode == http.StatusPartialContent {
		status = "206 Partial Content"
	}
	fmt.Fprintf(&h, "HTTP/1.1 %s\r\n", status)
	h.WriteString("Accept-Ranges: bytes\r\n")
	h.WriteString("Content-Type: audio/mpeg\r\n")
	if resp.ContentLength >= 0 {
		fmt.Fprintf(&h, "Content-Length: %d\r\n", resp.ContentLength)
	}
	if cr := resp.Header.Get("Content-Range"); cr != "" {
		fmt.Fprintf(&h, "Content-Range: %s\r\n", cr)
	}
	h.WriteString("Cache-Control: public, max-age=3600\r\n")
	h.WriteString("Connection: close\r\n\r\n")
	if _, err := io.WriteString(w, h.String()); err != nil {
		return
	}
	_, _ = io.Copy(w, resp.Body)
}

// serveMediaHead answers HEAD without downloading the body.
func serveMediaHead(w io.Writer, msg *message) {
	target, err := mediaTarget(requestLine(msg.hdr))
	if err != nil {
		writeStatus(w, 400, "")
		return
	}
	req, _ := http.NewRequest(http.MethodHead, target, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36")
	resp, err := mediaClient.Do(req)
	if err != nil {
		writeStatus(w, 502, "")
		return
	}
	defer resp.Body.Close()
	var h strings.Builder
	h.WriteString("HTTP/1.1 200 OK\r\n")
	h.WriteString("Accept-Ranges: bytes\r\nContent-Type: audio/mpeg\r\n")
	if resp.ContentLength >= 0 {
		fmt.Fprintf(&h, "Content-Length: %d\r\n", resp.ContentLength)
	}
	h.WriteString("Connection: close\r\n\r\n")
	_, _ = io.WriteString(w, h.String())
}

// mediaTarget decodes the ?u=<base64url> parameter of the request line.
func mediaTarget(line string) (string, error) {
	sp := strings.IndexByte(line, ' ')
	if sp < 0 {
		return "", fmt.Errorf("bad request line")
	}
	rest := line[sp+1:]
	if sp2 := strings.IndexByte(rest, ' '); sp2 >= 0 {
		rest = rest[:sp2]
	}
	u, err := url.Parse(rest)
	if err != nil {
		return "", err
	}
	enc := u.Query().Get("u")
	if enc == "" {
		return "", fmt.Errorf("missing u")
	}
	raw, err := base64.RawURLEncoding.DecodeString(enc)
	if err != nil {
		return "", err
	}
	target := string(raw)
	if !strings.HasPrefix(target, "http://") && !strings.HasPrefix(target, "https://") {
		return "", fmt.Errorf("bad target")
	}
	return target, nil
}

// requestLine returns the first line of a raw HTTP request (without CR/LF).
func requestLine(hdr []byte) string {
	if i := strings.IndexByte(string(hdr), '\r'); i >= 0 {
		return string(hdr[:i])
	}
	return strings.TrimSpace(string(hdr))
}

// headerValue returns one header value from the raw header block.
func headerValue(hdr []byte, name string) string {
	sc := bufio.NewScanner(strings.NewReader(string(hdr)))
	for sc.Scan() {
		line := sc.Text()
		i := strings.IndexByte(line, ':')
		if i <= 0 {
			continue
		}
		if strings.EqualFold(strings.TrimSpace(line[:i]), name) {
			return strings.TrimSpace(line[i+1:])
		}
	}
	return ""
}

// writeStatus writes a minimal error response.
func writeStatus(w io.Writer, code int, extra string) {
	text := http.StatusText(code)
	if text == "" {
		text = "Error"
	}
	fmt.Fprintf(w, "HTTP/1.1 %d %s\r\nContent-Length: 0\r\nConnection: close\r\n%s\r\n", code, text, extra)
}

var _ = net.IPv4len
var _ = strconv.Itoa
