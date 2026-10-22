// Package home implements the tiny TCP echo server of home_server.php
// (useful to watch what the speaker connects to).
package home

import (
	"log"
	"net"
)

// Server echoes received bytes back with a "Server: " prefix.
type Server struct {
	Addr string
}

// ListenAndServe accepts connections forever.
func (s *Server) ListenAndServe() error {
	addr := s.Addr
	if addr == "" {
		addr = "0.0.0.0:8883"
	}
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	log.Printf("[home] listening on %s", addr)
	for {
		c, err := ln.Accept()
		if err != nil {
			return err
		}
		go func(c net.Conn) {
			defer c.Close()
			log.Printf("[home] connect %s", c.RemoteAddr())
			buf := make([]byte, 8192)
			for {
				n, err := c.Read(buf)
				if n > 0 {
					log.Printf("[home] recv %d bytes: %q", n, string(buf[:n]))
					_, _ = c.Write(append([]byte("Server: "), buf[:n]...))
				}
				if err != nil {
					log.Printf("[home] close %s", c.RemoteAddr())
					return
				}
			}
		}(c)
	}
}
