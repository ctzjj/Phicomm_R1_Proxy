package music

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	kuwoSearchURL = "http://www.kuwo.cn/search/searchMusicBykeyWord"
	kuwoMobiURL   = "https://mobi.kuwo.cn/mobi.s"
	// Mobile client id required by the signed url endpoint.
	kuwoClientSource = "kwplayercar_ar_6.0.0.9_B_jiakong_vh.apk"
	kuwoUA           = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)

// Kuwo searches music on kuwo.cn (酷我).
//
// The plain anti.s endpoint only serves previews nowadays; the signed mobi.s
// endpoint (type=convert_url_with_sign) returns the full track, as used by
// github.com/guohuiyuan/music-lib.
type Kuwo struct {
	HTTP *http.Client
}

// NewKuwo returns a Kuwo provider.
func NewKuwo() *Kuwo {
	return &Kuwo{HTTP: &http.Client{Timeout: 12 * time.Second}}
}

// Name implements Source.
func (k *Kuwo) Name() string { return "kuwo" }

type kuwoSearchResp struct {
	AbsList []struct {
		MusicRID  string `json:"MUSICRID"`
		SongName  string `json:"SONGNAME"`
		Artist    string `json:"ARTIST"`
		Album     string `json:"ALBUM"`
		Duration  any    `json:"DURATION"`
		MInfo     string `json:"MINFO"`
		BitSwitch int    `json:"bitSwitch"`
	} `json:"abslist"`
}

// Search returns up to limit playable Kuwo tracks.
func (k *Kuwo) Search(ctx context.Context, keyword string, limit int) ([]Item, error) {
	if limit <= 0 || limit > 30 {
		limit = 20
	}
	q := url.Values{}
	q.Set("vipver", "1")
	q.Set("client", "kt")
	q.Set("ft", "music")
	q.Set("cluster", "0")
	q.Set("strategy", "2012")
	q.Set("encoding", "utf8")
	q.Set("rformat", "json")
	q.Set("mobi", "1")
	q.Set("issubtitle", "1")
	q.Set("show_copyright_off", "1")
	q.Set("pn", "0")
	q.Set("rn", strconv.Itoa(limit))
	q.Set("all", keyword)

	body, err := k.get(ctx, kuwoSearchURL+"?"+q.Encode())
	if err != nil {
		return nil, err
	}
	songs, err := parseKuwoSearchJSON(body)
	if err != nil {
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
		go func(i int, s kuwoSong) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			u, br, dur, err := k.songURL(ctx, s.rid)
			if err != nil || u == "" {
				return
			}
			it := NewItem()
			it.Title = s.title
			it.Artist = s.artist
			it.Album = s.album
			it.URL = u
			it.Bitrate = br
			if dur > 0 {
				it.Duration = dur * 1000
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

type kuwoSong struct {
	rid      string
	title    string
	artist   string
	album    string
	duration int // seconds
}

// parseKuwoSearchJSON parses the abslist JSON returned by
// www.kuwo.cn/search/searchMusicBykeyWord.
func parseKuwoSearchJSON(body []byte) ([]kuwoSong, error) {
	var resp kuwoSearchResp
	if err := json.Unmarshal(body, &resp); err != nil {
		return nil, fmt.Errorf("kuwo json: %w", err)
	}
	out := make([]kuwoSong, 0, len(resp.AbsList))
	for _, it := range resp.AbsList {
		if it.BitSwitch == 0 {
			continue
		}
		rid := strings.TrimPrefix(it.MusicRID, "MUSIC_")
		if rid == "" || it.SongName == "" {
			continue
		}
		out = append(out, kuwoSong{
			rid:      rid,
			title:    unescapeKuwo(it.SongName),
			artist:   unescapeKuwo(it.Artist),
			album:    unescapeKuwo(it.Album),
			duration: toInt(it.Duration),
		})
	}
	return out, nil
}

// songURL resolves the full mp3 url of one rid via the signed mobi endpoint.
func (k *Kuwo) songURL(ctx context.Context, rid string) (string, int, int, error) {
	for _, br := range []string{"320kmp3", "128kmp3"} {
		q := url.Values{}
		q.Set("f", "web")
		q.Set("source", kuwoClientSource)
		q.Set("from", "PC")
		q.Set("type", "convert_url_with_sign")
		q.Set("br", br)
		q.Set("rid", rid)
		q.Set("user", fmt.Sprintf("C_APK_guanwang_%d%d", time.Now().UnixNano(), rand.Intn(1000000)))
		body, err := k.get(ctx, kuwoMobiURL+"?"+q.Encode())
		if err != nil {
			continue
		}
		var resp struct {
			Code int `json:"code"`
			Data struct {
				URL      string `json:"url"`
				Bitrate  int    `json:"bitrate"`
				Duration int    `json:"duration"`
				Format   string `json:"format"`
			} `json:"data"`
		}
		if json.Unmarshal(body, &resp) != nil || resp.Data.URL == "" {
			continue
		}
		return resp.Data.URL, resp.Data.Bitrate, resp.Data.Duration, nil
	}
	return "", 0, 0, errors.New("kuwo: no playable url")
}

func (k *Kuwo) get(ctx context.Context, u string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", kuwoUA)
	req.Header.Set("Cookie", "kw_token=ABCDEFGHIJKLMNOP")
	ip := randomCNIP()
	req.Header.Set("X-Forwarded-For", ip)
	req.Header.Set("X-Real-IP", ip)
	resp, err := k.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("kuwo: http %d", resp.StatusCode)
	}
	return body, nil
}

var cnIPs = []string{"114.114.114.114", "223.5.5.5", "119.29.29.29", "180.76.76.76", "117.50.10.10"}

func randomCNIP() string { return cnIPs[rand.Intn(len(cnIPs))] }

func unescapeKuwo(s string) string {
	r := strings.NewReplacer(
		"&nbsp;", " ", "&amp;", "&", "&lt;", "<", "&gt;", ">", "&quot;", `"`, "&#39;", "'",
		`\\u0026`, "&", `\\u003c`, "<", `\\u003e`, ">",
	)
	return strings.TrimSpace(r.Replace(s))
}

func toInt(v any) int {
	switch x := v.(type) {
	case float64:
		return int(x)
	case string:
		n, _ := strconv.Atoi(strings.TrimSpace(x))
		return n
	}
	return 0
}
