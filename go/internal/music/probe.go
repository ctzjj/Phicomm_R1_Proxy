package music

import (
	"context"
	"io"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// probeResult is one candidate after verification.
type probeResult struct {
	it    Item
	lat   time.Duration
	ok    bool
	score int
	size  int64
	brate int
}

// ProbeOrder verifies every candidate url (a real ranged GET, not just a
// HEAD) and returns the playable ones ordered so that the R1 starts playback
// reliably and at the best quality:
//
//  1. urls served by a plain CDN (the R1 MediaPlayer gets stuck on some
//     object-store responses such as openresty's Content-Disposition/x-nos-*
//     headers: the track prepares but never starts)
//  2. bitrate (highest first)
//  3. latency (fastest first)
//
// Dead links (HTML error pages, 4xx/5xx, empty bodies) are dropped. When
// nothing is verifiable the input order is kept.
func ProbeOrder(ctx context.Context, items []Item) []Item {
	ch := make(chan probeResult, len(items))
	var wg sync.WaitGroup
	sem := make(chan struct{}, 8)
	for _, it := range items {
		wg.Add(1)
		go func(it Item) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			ch <- probeOne(ctx, it)
		}(it)
	}
	wg.Wait()
	close(ch)

	good := make([]probeResult, 0, len(items))
	for r := range ch {
		if !r.ok {
			continue
		}
		if r.brate > r.it.Bitrate {
			r.it.Bitrate = r.brate
		}
		if r.size > 0 {
			r.it.Size = r.size
		}
		good = append(good, r)
	}
	if len(good) == 0 {
		return items
	}
	sort.Slice(good, func(i, j int) bool {
		if good[i].score != good[j].score {
			return good[i].score > good[j].score
		}
		if good[i].it.Bitrate != good[j].it.Bitrate {
			return good[i].it.Bitrate > good[j].it.Bitrate
		}
		return good[i].lat < good[j].lat
	})
	out := make([]Item, 0, len(good))
	for _, r := range good {
		out = append(out, r.it)
	}
	if len(out) > 10 {
		out = out[:10]
	}
	return out
}

// probeClient is shared by every probe: a fresh client per candidate would
// open dozens of TLS connections at once and time out under load.
var probeClient = &http.Client{
	Timeout: 3 * time.Second,
	Transport: &http.Transport{
		MaxIdleConns:        64,
		MaxIdleConnsPerHost: 16,
		IdleConnTimeout:     30 * time.Second,
		DisableCompression:  true,
	},
}

// probeOne fetches the first 2 KiB of the stream and checks that it really is
// audio.
func probeOne(ctx context.Context, it Item) probeResult {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, it.URL, nil)
	if err != nil {
		return probeResult{it: it}
	}
	req.Header.Set("Range", "bytes=0-2047")
	cl := probeClient
	t0 := time.Now()
	resp, err := cl.Do(req)
	if err != nil {
		return probeResult{it: it}
	}
	defer resp.Body.Close()
	lat := time.Since(t0)

	head, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusPartialContent {
		return probeResult{it: it}
	}
	ct := strings.ToLower(resp.Header.Get("Content-Type"))
	if ct != "" && !strings.HasPrefix(ct, "audio/") &&
		!strings.HasPrefix(ct, "application/octet-stream") {
		return probeResult{it: it}
	}
	if !looksLikeAudio(head) {
		return probeResult{it: it}
	}
	srv := strings.ToLower(resp.Header.Get("Server"))
	// CDN compatibility score for the R1 player: nginx streams start most
	// reliably, object stores (openresty + Content-Disposition/x-nos-*) can
	// prepare without ever starting.
	score := 1
	if strings.Contains(srv, "nginx") {
		score = 2
	}
	if strings.Contains(srv, "openresty") {
		score = 0
	}
	size := contentRangeTotal(resp.Header.Get("Content-Range"))
	if size == 0 && resp.ContentLength > 64*1024 {
		// Only trust Content-Length when it looks like a whole file: a ranged
		// response reports just the requested bytes (e.g. 2048).
		size = resp.ContentLength
	}
	if size > 0 && size < 256*1024 { // an error page or a jingle, not a track
		return probeResult{it: it}
	}
	brate := it.Bitrate
	if brate == 0 && size > 0 && it.Duration > 0 {
		// Duration is in milliseconds: size*8/duration_ms == kbps.
		brate = int(size * 8 / int64(it.Duration))
	}
	// Reject truncated previews: a full track needs roughly
	// bitrate(kbps) * duration(ms) / 8 bytes.
	if it.Duration == 0 && size > 0 && brate > 0 {
		it.Duration = int(size * 8 / int64(brate))
	}
	if size > 0 && it.Duration > 0 {
		expect := int64(96) * int64(it.Duration) / 8 // assume at least 96 kbps
		if int64(brate) > 96 {
			expect = int64(brate) * int64(it.Duration) / 8
		}
		if size*2 < expect {
			return probeResult{it: it}
		}
	}
	return probeResult{it: it, lat: lat, ok: true, score: score, size: size, brate: brate}
}

// looksLikeAudio sniffs the container magic of the first bytes.
func looksLikeAudio(b []byte) bool {
	if len(b) >= 3 && string(b[:3]) == "ID3" {
		return true
	}
	if len(b) >= 2 && b[0] == 0xFF && b[1]&0xE0 == 0xE0 {
		return true // MPEG audio frame sync
	}
	if len(b) >= 4 && (string(b[:4]) == "OggS" || string(b[:4]) == "fLaC") {
		return true
	}
	if len(b) >= 12 && string(b[4:8]) == "ftyp" {
		return true // mp4/m4a
	}
	return false
}

// contentRangeTotal parses the total from "bytes 0-2047/123456".
func contentRangeTotal(cr string) int64 {
	if cr == "" {
		return 0
	}
	if i := strings.LastIndexByte(cr, '/'); i >= 0 {
		if n, err := strconv.ParseInt(strings.TrimSpace(cr[i+1:]), 10, 64); err == nil {
			return n
		}
	}
	return 0
}
