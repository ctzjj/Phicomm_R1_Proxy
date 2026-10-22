// Package webui is the embedded web console: live settings + log tail.
package webui

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/asr"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/logbuf"
)

//go:embed index.html
var indexHTML []byte

// Server is the console HTTP server.
type Server struct {
	Addr     string
	Settings *asr.Store
	Logs     *logbuf.Buffer
	Status   func() asr.Status
	Save     func() error
}

// ListenAndServe blocks serving the console.
func (s *Server) ListenAndServe() error {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write(indexHTML)
	})
	mux.HandleFunc("/api/config", s.handleConfig)
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(s.Status())
	})
	mux.HandleFunc("/api/logs", s.handleLogs)
	log.Printf("[web] console on %s", s.Addr)
	return http.ListenAndServe(s.Addr, mux)
}

func (s *Server) handleConfig(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	switch r.Method {
	case http.MethodGet:
		_ = json.NewEncoder(w).Encode(s.Settings.Get())
	case http.MethodPost, http.MethodPut:
		var in asr.Settings
		if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		out := s.Settings.Update(in)
		if s.Save != nil {
			if err := s.Save(); err != nil {
				log.Printf("[web] save settings: %v", err)
			}
		}
		log.Printf("[web] settings updated: upstream=%s media=%s music=%v nlu=%s",
			out.Upstream, out.MediaBase, out.Music, out.NLUMode)
		_ = json.NewEncoder(w).Encode(out)
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}

// handleLogs streams log lines as Server-Sent Events.
func (s *Server) handleLogs(w http.ResponseWriter, r *http.Request) {
	fl, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}
	h := w.Header()
	h.Set("Content-Type", "text/event-stream")
	h.Set("Cache-Control", "no-cache")
	h.Set("Connection", "keep-alive")
	h.Set("X-Accel-Buffering", "no")

	write := func(line string) bool {
		line = strings.ReplaceAll(line, "\r", "")
		if _, err := fmt.Fprintf(w, "data: %s\n\n", line); err != nil {
			return false
		}
		fl.Flush()
		return true
	}
	for _, line := range s.Logs.Lines() {
		if !write(line) {
			return
		}
	}
	ch, cancel := s.Logs.Subscribe()
	defer cancel()
	ping := time.NewTicker(15 * time.Second)
	defer ping.Stop()
	for {
		select {
		case line, ok := <-ch:
			if !ok || !write(line) {
				return
			}
		case <-ping.C:
			if _, err := fmt.Fprint(w, ": ping\n\n"); err != nil {
				return
			}
			fl.Flush()
		case <-r.Context().Done():
			return
		}
	}
}
