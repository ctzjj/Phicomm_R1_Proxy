// Package asr implements the ASR interception proxy: point
// asrv3.hivoice.cn at this server, forward every request to the upstream
// ASR service, optionally dump the uploaded audio for offline analysis,
// and replace music answers with search results before returning them to
// the speaker.
package asr

import (
	"bufio"
	"bytes"
	"context"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/music"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/util"
)

// Server is a one-request-at-a-time HTTP relay over plain TCP.
type Server struct {
	Addr     string // ":80"
	Upstream string // "47.102.50.144:80"
	Verbose  bool
	DumpDir  string // when set, every request/response is written to this directory
	AudioDir string // when set, each utterance is written as <dir>/uttNN_<sid>.ogg
	Forward  string // when set, each utterance Ogg is POSTed to this URL
	seq      uint64
	cap      *capture
}

// message is one HTTP message: raw is what gets forwarded, hdr the header
// block and body the de-chunked payload.
type message struct {
	raw  []byte
	hdr  []byte
	body []byte
}

// ListenAndServe accepts connections until ctx is cancelled.
func (s *Server) ListenAndServe(ctx context.Context) error {
	addr := s.Addr
	if addr == "" {
		addr = ":80"
	}
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	go func() {
		<-ctx.Done()
		_ = ln.Close()
	}()
	log.Printf("[asr] listening on %s, upstream %s (point asrv3.hivoice.cn here)", addr, s.Upstream)
	if s.DumpDir != "" {
		log.Printf("[asr] dumping requests/responses to %s", s.DumpDir)
	}
	if s.AudioDir != "" || s.Forward != "" {
		dir := s.AudioDir
		if dir == "" {
			dir = "."
		}
		s.cap = newCapture(dir, s.Forward)
		log.Printf("[asr] audio capture on: dir=%s forward=%q", dir, s.Forward)
	}
	for {
		conn, err := ln.Accept()
		if err != nil {
			return err
		}
		go s.handle(conn)
	}
}

func (s *Server) handle(c net.Conn) {
	defer c.Close()
	br := bufio.NewReaderSize(c, 64<<10)
	for {
		_ = c.SetReadDeadline(time.Now().Add(120 * time.Second))
		msg, err := readMessage(br, 32<<20)
		if err != nil {
			return
		}
		seq := atomic.AddUint64(&s.seq, 1)
		if s.DumpDir != "" {
			s.dump(seq, "req", msg.hdr, msg.body)
		}
		if s.cap != nil {
			s.cap.add(msg.hdr, msg.body)
		}
		out := s.process(msg)
		if s.DumpDir != "" {
			h, b := splitHTTP(out)
			s.dump(seq, "resp", h, b)
		}
		_ = c.SetWriteDeadline(time.Now().Add(30 * time.Second))
		if _, err := c.Write(out); err != nil {
			return
		}
	}
}

// dump writes header/body files and appends a one-line summary.
func (s *Server) dump(seq uint64, kind string, hdr, body []byte) {
	_ = os.MkdirAll(s.DumpDir, 0o755)
	base := filepath.Join(s.DumpDir, fmt.Sprintf("%04d_%s", seq, kind))
	_ = os.WriteFile(base+".hdr", hdr, 0o644)
	_ = os.WriteFile(base+".bin", body, 0o644)

	line := fmt.Sprintf("%s #%04d %s %s\n",
		time.Now().Format("2006-01-02 15:04:05.000"), seq, kind, oneLine(string(hdr)))
	_ = os.WriteFile(base+".txt", []byte(line+hex.Dump(firstN(body, 256))), 0o644)
	if f, err := os.OpenFile(filepath.Join(s.DumpDir, "index.log"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
		_, _ = f.WriteString(line + fmt.Sprintf("    body=%d first32=%s\n", len(body), hex.EncodeToString(firstN(body, 32))))
		_ = f.Close()
	}
	if s.Verbose {
		log.Printf("[asr] #%04d %s %s body=%d first32=%s", seq, kind, oneLine(string(hdr)), len(body), hex.EncodeToString(firstN(body, 32)))
	}
}

func (s *Server) process(msg *message) []byte {
	upAddr := s.Upstream
	if upAddr == "" {
		upAddr = "47.102.50.144:80"
	}
	up, err := net.DialTimeout("tcp", upAddr, 10*time.Second)
	if err != nil {
		log.Printf("[asr] upstream dial: %v", err)
		return []byte("HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
	}
	defer up.Close()
	_ = up.SetDeadline(time.Now().Add(60 * time.Second))
	if _, err := up.Write(msg.raw); err != nil {
		log.Printf("[asr] upstream write: %v", err)
		return []byte("HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
	}
	resp, err := readMessage(bufio.NewReaderSize(up, 64<<10), 32<<20)
	if err != nil {
		log.Printf("[asr] upstream read: %v", err)
		return []byte("HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
	}
	if s.Verbose {
		log.Printf("[asr] <- %d bytes", len(resp.raw))
	}

	d, err := util.Parse(resp.raw)
	if err != nil {
		return resp.raw
	}
	// Only JSON bodies can carry a music intent; anything else is passed
	// through byte-for-byte.
	if _, isText := d.Body.(string); isText {
		return resp.raw
	}
	p := music.New(d)
	if !p.IsMusic() {
		return resp.raw
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := p.Search(ctx); err != nil {
		log.Printf("[asr] search %q: %v", p.Keyword(), err)
	}
	if s.Verbose {
		log.Printf("[asr] music intent keyword=%q", p.Keyword())
	}
	return d.Build()
}

// readMessage reads one HTTP message: header terminated by CRLFCRLF plus
// either Content-Length bytes, a chunked body, or everything until EOF.
func readMessage(br *bufio.Reader, max int) (*message, error) {
	var hdr []byte
	for {
		line, err := br.ReadBytes('\n')
		if err != nil {
			return nil, err
		}
		hdr = append(hdr, line...)
		if len(hdr) > 64<<10 {
			return nil, errors.New("header too large")
		}
		if bytes.HasSuffix(hdr, []byte("\r\n\r\n")) {
			break
		}
	}
	if headerHas(hdr, "Transfer-Encoding", "chunked") {
		raw := append([]byte(nil), hdr...)
		var body []byte
		for {
			line, err := br.ReadBytes('\n')
			if err != nil {
				return nil, err
			}
			raw = append(raw, line...)
			sizeStr := strings.TrimSpace(string(line))
			if i := strings.IndexByte(sizeStr, ';'); i >= 0 {
				sizeStr = sizeStr[:i]
			}
			size, err := strconv.ParseInt(sizeStr, 16, 64)
			if err != nil {
				return nil, fmt.Errorf("bad chunk size %q", sizeStr)
			}
			if size == 0 {
				for {
					tl, err := br.ReadBytes('\n')
					if err != nil {
						return nil, err
					}
					raw = append(raw, tl...)
					if len(bytes.TrimRight(tl, "\r\n")) == 0 {
						return &message{raw: raw, hdr: hdr, body: body}, nil
					}
				}
			}
			if size > int64(max) || len(raw)+int(size) > max {
				return nil, errors.New("body too large")
			}
			buf := make([]byte, size)
			if _, err := io.ReadFull(br, buf); err != nil {
				return nil, err
			}
			body = append(body, buf...)
			raw = append(raw, buf...)
			crlf := make([]byte, 2)
			if _, err := io.ReadFull(br, crlf); err != nil {
				return nil, err
			}
			raw = append(raw, crlf...)
		}
	}
	cl, ok := contentLength(hdr)
	if !ok {
		rest, err := io.ReadAll(io.LimitReader(br, int64(max)))
		if err != nil {
			return nil, err
		}
		return &message{raw: append(hdr, rest...), hdr: hdr, body: rest}, nil
	}
	if cl <= 0 {
		return &message{raw: hdr, hdr: hdr}, nil
	}
	if cl > max {
		return nil, errors.New("body too large")
	}
	body := make([]byte, cl)
	if _, err := io.ReadFull(br, body); err != nil {
		return nil, err
	}
	return &message{raw: append(hdr, body...), hdr: hdr, body: body}, nil
}

func contentLength(hdr []byte) (int, bool) {
	for _, line := range bytes.Split(hdr, []byte("\r\n")) {
		i := bytes.IndexByte(line, ':')
		if i <= 0 {
			continue
		}
		if bytes.EqualFold(bytes.TrimSpace(line[:i]), []byte("Content-Length")) {
			n, err := strconv.Atoi(string(bytes.TrimSpace(line[i+1:])))
			if err != nil {
				return 0, false
			}
			return n, true
		}
	}
	return 0, false
}

func headerHas(hdr []byte, name, value string) bool {
	for _, line := range bytes.Split(hdr, []byte("\r\n")) {
		i := bytes.IndexByte(line, ':')
		if i <= 0 {
			continue
		}
		if bytes.EqualFold(bytes.TrimSpace(line[:i]), []byte(name)) &&
			strings.Contains(strings.ToLower(string(line[i+1:])), value) {
			return true
		}
	}
	return false
}

// splitHTTP splits a raw HTTP message into header block and body, decoding
// a chunked body when present (for readable dumps).
func splitHTTP(raw []byte) (hdr, body []byte) {
	i := bytes.Index(raw, []byte("\r\n\r\n"))
	if i < 0 {
		return raw, nil
	}
	hdr, body = raw[:i+4], raw[i+4:]
	if headerHas(hdr, "Transfer-Encoding", "chunked") {
		body = dechunk(body)
	}
	return hdr, body
}

func dechunk(b []byte) []byte {
	var out []byte
	for {
		nl := bytes.IndexByte(b, '\n')
		if nl < 0 {
			return out
		}
		sizeStr := strings.TrimSpace(string(b[:nl]))
		if i := strings.IndexByte(sizeStr, ';'); i >= 0 {
			sizeStr = sizeStr[:i]
		}
		size, err := strconv.ParseInt(sizeStr, 16, 64)
		if err != nil || size < 0 {
			return out
		}
		b = b[nl+1:]
		if size == 0 {
			return out
		}
		if int64(len(b)) < size {
			return out
		}
		out = append(out, b[:size]...)
		b = b[size:]
		if len(b) >= 2 && b[0] == '\r' && b[1] == '\n' {
			b = b[2:]
		} else if len(b) >= 1 && b[0] == '\n' {
			b = b[1:]
		}
	}
}

func oneLine(s string) string {
	s = strings.ReplaceAll(s, "\r", "")
	s = strings.ReplaceAll(s, "\n", " | ")
	if len(s) > 400 {
		s = s[:400] + "..."
	}
	return s
}

func firstN(b []byte, n int) []byte {
	if len(b) < n {
		return b
	}
	return b[:n]
}
