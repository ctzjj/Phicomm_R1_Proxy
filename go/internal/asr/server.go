// Package asr implements the ASR interception proxy of the PHP
// asr_proxy.php: point asrv3.hivoice.cn at this server, forward every
// request to the upstream ASR service, and replace music answers with
// search results before returning them to the speaker.
package asr

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"io"
	"log"
	"net"
	"strconv"
	"time"

	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/music"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/util"
)

// Server is a one-request-at-a-time HTTP relay over plain TCP.
type Server struct {
	Addr     string // ":80"
	Upstream string // "47.102.50.144:80"
	Verbose  bool
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
		_ = c.SetReadDeadline(time.Now().Add(60 * time.Second))
		req, err := readMessage(br, 8<<20)
		if err != nil {
			return
		}
		out := s.process(req)
		_ = c.SetWriteDeadline(time.Now().Add(30 * time.Second))
		if _, err := c.Write(out); err != nil {
			return
		}
	}
}

func (s *Server) process(req []byte) []byte {
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
	_ = up.SetDeadline(time.Now().Add(30 * time.Second))
	if _, err := up.Write(req); err != nil {
		log.Printf("[asr] upstream write: %v", err)
		return []byte("HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
	}
	resp, err := readMessage(bufio.NewReaderSize(up, 64<<10), 8<<20)
	if err != nil {
		log.Printf("[asr] upstream read: %v", err)
		return []byte("HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
	}
	if s.Verbose {
		log.Printf("[asr] <- %d bytes", len(resp))
	}

	d, err := util.Parse(resp)
	if err != nil {
		return resp
	}
	// Only JSON bodies can carry a music intent; anything else is passed
	// through byte-for-byte.
	if _, isText := d.Body.(string); isText {
		return resp
	}
	p := music.New(d)
	if !p.IsMusic() {
		return resp
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
// Content-Length bytes of body (or everything until EOF when the length is
// missing, as some servers do for error replies).
func readMessage(br *bufio.Reader, max int) ([]byte, error) {
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
	cl, ok := contentLength(hdr)
	if !ok {
		rest, err := io.ReadAll(io.LimitReader(br, int64(max)))
		if err != nil {
			return nil, err
		}
		return append(hdr, rest...), nil
	}
	if cl <= 0 {
		return hdr, nil
	}
	if cl > max {
		return nil, errors.New("body too large")
	}
	body := make([]byte, cl)
	if _, err := io.ReadFull(br, body); err != nil {
		return nil, err
	}
	return append(hdr, body...), nil
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
