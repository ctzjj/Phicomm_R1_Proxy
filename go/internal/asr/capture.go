package asr

import (
	"bytes"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/audio"
)

// capture groups the /trafficRouter/cs Opus chunks by session id, writes one
// Ogg/Opus file per utterance and (optionally) forwards it to a downstream
// ASR / LLM service.
type capture struct {
	mu   sync.Mutex
	st   *Store
	n    int
	sess map[string]*session
}

type session struct {
	sid  string
	pkts [][]byte
	at   time.Time
}

func newCapture(st *Store) *capture {
	c := &capture{st: st, sess: map[string]*session{}}
	go c.sweep()
	return c
}

// FinalizeSID removes and returns the buffered utterance of one session
// (used by the external-NLU mode, which must answer with its own result).
func (c *capture) FinalizeSID(hdr []byte) (string, []byte) {
	sid := audio.SessionID(hdr)
	if sid == "" {
		sid = "unknown"
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	s := c.sess[sid]
	if s == nil || len(s.pkts) == 0 {
		return "", nil
	}
	delete(c.sess, sid)
	return sid, audio.OggOpus(s.pkts)
}

// add inspects one intercepted request. It never blocks the proxy.
func (c *capture) add(hdr, body []byte) {
	if !bytes.Contains(hdr, []byte("/trafficRouter/cs")) {
		return
	}
	sid := audio.SessionID(hdr)
	if sid == "" {
		sid = "unknown"
	}
	pkts := audio.ParseChunks(body)

	c.mu.Lock()
	defer c.mu.Unlock()
	s := c.sess[sid]
	if s != nil && time.Since(s.at) > 3*time.Second && len(pkts) > 0 {
		// a new utterance on a recycled session id
		c.finalizeLocked(s)
		s = nil
	}
	if len(pkts) > 0 {
		if s == nil {
			s = &session{sid: sid}
			c.sess[sid] = s
		}
		s.pkts = append(s.pkts, pkts...)
		s.at = time.Now()
		return
	}
	// empty body: the client asks for the final NLU result -> utterance done
	if s != nil {
		c.finalizeLocked(s)
	}
}

func (c *capture) sweep() {
	for range time.Tick(time.Second) {
		c.mu.Lock()
		for _, s := range c.sess {
			if time.Since(s.at) > 3*time.Second {
				c.finalizeLocked(s)
			}
		}
		c.mu.Unlock()
	}
}

func (c *capture) finalizeLocked(s *session) {
	delete(c.sess, s.sid)
	if len(s.pkts) == 0 {
		return
	}
	c.n++
	packets := s.pkts
	ogg := audio.OggOpus(packets)
	snap := c.st.Snapshot()
	if snap.AudioDir != "" {
		name := fmt.Sprintf("utt%02d_%s.ogg", c.n, safeName(s.sid))
		path := filepath.Join(snap.AudioDir, name)
		if err := os.MkdirAll(snap.AudioDir, 0o755); err == nil {
			if err := os.WriteFile(path, ogg, 0o644); err != nil {
				log.Printf("[asr] audio write %s: %v", path, err)
			} else {
				log.Printf("[asr] utterance %s: %d packets, %.2fs -> %s",
					s.sid, len(packets), float64(len(packets))*0.02, path)
			}
		}
	}
	if snap.Forward != "" {
		go c.post(snap.Forward, s.sid, packets, ogg)
	}
}

func (c *capture) post(forward, sid string, packets [][]byte, ogg []byte) {
	req, err := http.NewRequest(http.MethodPost, forward, bytes.NewReader(ogg))
	if err != nil {
		log.Printf("[asr] forward: %v", err)
		return
	}
	req.Header.Set("Content-Type", "audio/ogg")
	req.Header.Set("X-R1-SID", sid)
	req.Header.Set("X-R1-Packets", fmt.Sprint(len(packets)))
	req.Header.Set("X-R1-Sample-Rate", "16000")
	req.Header.Set("X-R1-Channels", "1")
	cl := &http.Client{Timeout: 30 * time.Second}
	resp, err := cl.Do(req)
	if err != nil {
		log.Printf("[asr] forward %s: %v", forward, err)
		return
	}
	defer resp.Body.Close()
	log.Printf("[asr] forwarded %s (%d bytes) -> %s", sid, len(ogg), resp.Status)
}

func safeName(s string) string {
	b := []byte(s)
	for i, c := range b {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '-' || c == '.') {
			b[i] = '_'
		}
	}
	if len(b) > 40 {
		b = b[:40]
	}
	return string(b)
}
