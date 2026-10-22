package music

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"sync"
	"time"
)

// GDStudio queries the public GD Studio aggregation API. Only the netease
// source is available without an api key, but it is an independent route to
// Netease (different host/protocol than the linux/forward path), which makes
// the search resilient when one of them breaks.
type GDStudio struct {
	HTTP *http.Client
	Base string
}

// NewGDStudio returns a GD Studio provider.
func NewGDStudio() *GDStudio {
	// The public instance is behind Cloudflare; force IPv4 because the IPv6
	// route is frequently reset by the local ISP.
	tr := &http.Transport{
		ForceAttemptHTTP2: false,
		DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
			d := &net.Dialer{Timeout: 8 * time.Second}
			return d.DialContext(ctx, "tcp4", addr)
		},
	}
	return &GDStudio{
		HTTP: &http.Client{Timeout: 12 * time.Second, Transport: tr},
		Base: "https://music-api.gdstudio.xyz/api.php",
	}
}

// Name implements Source.
func (g *GDStudio) Name() string { return "gdstudio" }

type gdSong struct {
	ID     json.RawMessage `json:"id"`
	Name   string          `json:"name"`
	Artist []string        `json:"artist"`
	Album  string          `json:"album"`
	PicID  string          `json:"pic_id"`
}

// Search returns up to limit playable tracks from GD Studio.
func (g *GDStudio) Search(ctx context.Context, keyword string, limit int) ([]Item, error) {
	if limit <= 0 || limit > 20 {
		limit = 20
	}
	q := url.Values{
		"types":  {"search"},
		"source": {"netease"},
		"name":   {keyword},
		"count":  {strconv.Itoa(limit)},
		"pages":  {"1"},
	}
	var songs []gdSong
	if err := g.getJSON(ctx, g.Base+"?"+q.Encode(), &songs); err != nil {
		return nil, err
	}
	if len(songs) > limit {
		songs = songs[:limit]
	}

	items := make([]Item, len(songs))
	var wg sync.WaitGroup
	sem := make(chan struct{}, 4)
	for i, s := range songs {
		wg.Add(1)
		go func(i int, s gdSong) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			id := rawID(s.ID)
			if id == "" {
				return
			}
			u, size, br, err := g.songURL(ctx, id)
			if err != nil || u == "" {
				return
			}
			it := NewItem()
			it.Title = s.Name
			it.Album = s.Album
			if len(s.Artist) > 0 {
				it.Artist = s.Artist[0]
			}
			it.URL = u
			it.Bitrate = br
			it.Size = size
			if it.Bitrate == 0 {
				it.Bitrate = 320
			}
			if size > 0 && it.Bitrate > 0 {
				it.Duration = int(size * 8 / int64(it.Bitrate))
			}
			items[i] = *it
		}(i, s)
	}
	wg.Wait()
	out := make([]Item, 0, len(items))
	for _, it := range items {
		if it.URL != "" {
			out = append(out, it)
		}
	}
	return out, nil
}

// songURL resolves the direct url of one Netease id.
func (g *GDStudio) songURL(ctx context.Context, id string) (string, int64, int, error) {
	q := url.Values{
		"types":  {"url"},
		"source": {"netease"},
		"id":     {id},
		"br":     {"320"},
	}
	var res struct {
		URL  string `json:"url"`
		BR   int    `json:"br"`
		Size int64  `json:"size"`
	}
	if err := g.getJSON(ctx, g.Base+"?"+q.Encode(), &res); err != nil {
		return "", 0, 0, err
	}
	if res.URL == "" {
		return "", 0, 0, fmt.Errorf("gdstudio: empty url")
	}
	return res.URL, res.Size, res.BR, nil
}

func (g *GDStudio) getJSON(ctx context.Context, u string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", neteaseUA)
	resp, err := g.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("gdstudio: http %d", resp.StatusCode)
	}
	return json.Unmarshal(body, out)
}

// rawID accepts both "123" and 123.
func rawID(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}
	s := string(raw)
	if len(s) >= 2 && s[0] == '"' {
		var v string
		if json.Unmarshal(raw, &v) == nil {
			return v
		}
		return ""
	}
	return s
}
