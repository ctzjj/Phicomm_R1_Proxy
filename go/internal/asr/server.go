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
	"sync"
	"sync/atomic"
	"time"

	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/audio"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/music"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/util"
)

// Server is a one-request-at-a-time HTTP relay over plain TCP.
type Server struct {
	Addr     string // ":80"
	Verbose  bool
	Settings *Store // live configuration (editable from the web console)
	seq      uint64
	cap      *capture
	dns      *upstreamResolver

	start      time.Time
	intercepts atomic.Uint64
	musicHits  atomic.Uint64
	nluCalls   atomic.Uint64
	errMu      sync.Mutex
	lastErr    string
}

// Status is the snapshot served by the web console.
type Status struct {
	Uptime        string `json:"uptime"`
	Intercepted   uint64 `json:"intercepted"`
	MusicReplaced uint64 `json:"musicReplaced"`
	NLUCalls      uint64 `json:"nluCalls"`
	LastError     string `json:"lastError"`
}

// Status returns the current counters.
func (s *Server) Status() Status {
	s.errMu.Lock()
	last := s.lastErr
	s.errMu.Unlock()
	return Status{
		Uptime:        time.Since(s.start).Round(time.Second).String(),
		Intercepted:   s.intercepts.Load(),
		MusicReplaced: s.musicHits.Load(),
		NLUCalls:      s.nluCalls.Load(),
		LastError:     last,
	}
}

func (s *Server) setErr(err error) {
	if err == nil {
		return
	}
	s.errMu.Lock()
	s.lastErr = err.Error()
	s.errMu.Unlock()
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
	s.start = time.Now()
	snap := s.Settings.Snapshot()
	s.dns = newUpstreamResolver(snap.DNS)
	if snap.Upstream == "" {
		if ip, err := s.dns.Resolve(ctx, snap.DNS); err == nil {
			log.Printf("[asr] resolved %s -> %s (via %s)", upstreamHost, ip, snap.DNS)
		} else {
			log.Printf("[asr] resolve %s failed: %v", upstreamHost, err)
		}
	}
	log.Printf("[asr] listening on %s, upstream %s (point asrv3.hivoice.cn here)", addr, snap.Upstream)
	if snap.DumpDir != "" {
		log.Printf("[asr] dumping requests/responses to %s", snap.DumpDir)
	}
	s.cap = newCapture(s.Settings)
	if snap.AudioDir != "" || snap.Forward != "" || snap.NLUMode == "custom" {
		log.Printf("[asr] audio capture on: dir=%q forward=%q nlu=%s", snap.AudioDir, snap.Forward, snap.NLUMode)
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
		snap := s.Settings.Snapshot()
		s.intercepts.Add(1)
		seq := atomic.AddUint64(&s.seq, 1)
		if snap.DumpDir != "" {
			s.dump(snap.DumpDir, seq, "req", msg.hdr, msg.body)
		}
		if isMediaRequest(msg.hdr) {
			_ = c.SetWriteDeadline(time.Now().Add(60 * time.Second))
			serveMedia(c, msg)
			return
		}
		// External NLU: answer the final request with our own service result.
		if snap.NLUMode == "custom" && snap.NLUURL != "" && isFinalRequest(msg.hdr) {
			if sid, ogg := s.cap.FinalizeSID(msg.hdr); ogg != nil {
				s.nluCalls.Add(1)
				if body, err := postNLU(snap, sid, ogg); err == nil {
					out := nluResponse(sid, body)
					if snap.DumpDir != "" {
						h, b := splitHTTP(out)
						s.dump(snap.DumpDir, seq, "resp", h, b)
					}
					_ = c.SetWriteDeadline(time.Now().Add(30 * time.Second))
					if _, err := c.Write(out); err != nil {
						return
					}
					continue
				} else {
					log.Printf("[asr] custom nlu: %v (falling back to cloud)", err)
					s.setErr(err)
				}
			}
		}
		s.cap.add(msg.hdr, msg.body)
		out := s.process(msg, snap)
		if snap.DumpDir != "" {
			h, b := splitHTTP(out)
			s.dump(snap.DumpDir, seq, "resp", h, b)
		}
		_ = c.SetWriteDeadline(time.Now().Add(30 * time.Second))
		if _, err := c.Write(out); err != nil {
			return
		}
	}
}

// dump writes header/body files and appends a one-line summary.
func (s *Server) dump(dir string, seq uint64, kind string, hdr, body []byte) {
	if dir == "" {
		return
	}
	_ = os.MkdirAll(dir, 0o755)
	base := filepath.Join(dir, fmt.Sprintf("%04d_%s", seq, kind))
	_ = os.WriteFile(base+".hdr", hdr, 0o644)
	_ = os.WriteFile(base+".bin", body, 0o644)

	line := fmt.Sprintf("%s #%04d %s %s\n",
		time.Now().Format("2006-01-02 15:04:05.000"), seq, kind, oneLine(string(hdr)))
	_ = os.WriteFile(base+".txt", []byte(line+hex.Dump(firstN(body, 256))), 0o644)
	if f, err := os.OpenFile(filepath.Join(dir, "index.log"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
		_, _ = f.WriteString(line + fmt.Sprintf("    body=%d first32=%s\n", len(body), hex.EncodeToString(firstN(body, 32))))
		_ = f.Close()
	}
	if s.Verbose {
		log.Printf("[asr] #%04d %s %s body=%d first32=%s", seq, kind, oneLine(string(hdr)), len(body), hex.EncodeToString(firstN(body, 32)))
	}
}

func (s *Server) process(msg *message, snap Snapshot) []byte {
	upAddr := snap.Upstream
	if upAddr == "" {
		ip, err := s.dns.Resolve(context.Background(), snap.DNS)
		if err != nil {
			log.Printf("[asr] upstream resolve: %v", err)
			s.setErr(err)
			return []byte("HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
		}
		upAddr = ip
	}
	up, err := net.DialTimeout("tcp", upAddr, 10*time.Second)
	if err != nil {
		log.Printf("[asr] upstream dial %s: %v", upAddr, err)
		s.dns.Invalidate()
		s.setErr(err)
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
	// Skill routing: first matching rule wins. "builtin" falls through to the
	// music handling / passthrough below.
	if len(snap.Skills) > 0 {
		code, text := cloudFields(d.Body)
		if sk := matchSkill(snap.Skills, code, text); sk != nil {
			sid := audioSessionID(msg.hdr)
			if out, handled := runSkill(*sk, sid, code, text); handled {
				log.Printf("[asr] skill %q handled code=%s text=%q", sk.Name, code, text)
				return out
			}
		}
	}
	if !snap.Music {
		return resp.raw
	}
	p := music.New(d)
	p.MediaBase = snap.MediaBase
	if !p.IsMusic() {
		return resp.raw
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := p.Search(ctx); err != nil {
		log.Printf("[asr] search %q: %v", p.Keyword(), err)
		s.setErr(err)
	} else {
		s.musicHits.Add(1)
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
		// A response without Content-Length runs until the connection closes,
		// but a request without one simply has no body (reading to EOF would
		// hang on keep-alive connections such as the /media endpoint).
		if bytes.HasPrefix(hdr, []byte("HTTP/")) {
			rest, err := io.ReadAll(io.LimitReader(br, int64(max)))
			if err != nil {
				return nil, err
			}
			return &message{raw: append(hdr, rest...), hdr: hdr, body: rest}, nil
		}
		return &message{raw: hdr, hdr: hdr}, nil
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

// audioSessionID extracts the session id from a request header block.
func audioSessionID(hdr []byte) string {
	return audio.SessionID(hdr)
}
