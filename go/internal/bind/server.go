// Package bind implements the binding helper of the PHP bind.php: the
// speaker queries /getUserInfo on aios-home.hivoice.cn, and answering
// {"status":"0"} makes it consider itself bound.
package bind

import (
	"log"
	"net/http"
)

// Server answers the binding request.
type Server struct {
	Addr string
}

// Handler returns the HTTP handler (useful for tests).
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/getUserInfo", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; charset=UTF-8")
		_, _ = w.Write([]byte(`{"status":"0"}`))
	})
	mux.HandleFunc("/favicon.ico", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; charset=UTF-8")
		_, _ = w.Write([]byte("<h1>Hello World</h1>"))
	})
	return mux
}

// ListenAndServe starts the server.
func (s *Server) ListenAndServe() error {
	addr := s.Addr
	if addr == "" {
		addr = "0.0.0.0:19999"
	}
	log.Printf("[bind] listening on %s (point aios-home.hivoice.cn here)", addr)
	return http.ListenAndServe(addr, s.Handler())
}
