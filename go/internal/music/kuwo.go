package music

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	kuwoSearchURL = "http://search.kuwo.cn/r.s"
	kuwoURLURL    = "http://antiserver.kuwo.cn/anti.s"
	kuwoUA        = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)

// Kuwo searches music on kuwo.cn (酷我).
type Kuwo struct {
	HTTP *http.Client
}

// NewKuwo returns a Kuwo provider.
func NewKuwo() *Kuwo {
	return &Kuwo{HTTP: &http.Client{Timeout: 12 * time.Second}}
}

// Name implements Source.
func (k *Kuwo) Name() string { return "kuwo" }

type kuwoSong struct {
	rid      string
	title    string
	artist   string
	album    string
	formats  string
	minfo    string
	bitrate  int
	duration int // ms
}

// Search returns up to limit playable Kuwo tracks.
func (k *Kuwo) Search(ctx context.Context, keyword string, limit int) ([]Item, error) {
	if limit <= 0 || limit > 30 {
		limit = 20
	}
	q := url.Values{
		"all":      {keyword},
		"ft":       {"music"},
		"itemset":  {"web_2013"},
		"client":   {"kt"},
		"pn":       {"0"},
		"rn":       {strconv.Itoa(limit)},
		"rformat":  {"json"},
		"encoding": {"utf8"},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, kuwoSearchURL+"?"+q.Encode(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", kuwoUA)
	resp, err := k.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("kuwo: http %d", resp.StatusCode)
	}
	songs := parseKuwoSearch(string(body))
	if len(songs) > limit {
		songs = songs[:limit]
	}

	// Resolve the playable url of every song concurrently (bounded).
	items := make([]Item, len(songs))
	var wg sync.WaitGroup
	sem := make(chan struct{}, 2)
	for i, s := range songs {
		wg.Add(1)
		go func(i int, s kuwoSong) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			u, err := k.songURL(ctx, s.rid)
			if err != nil || u == "" {
				return
			}
			it := NewItem()
			it.Title = s.title
			it.Artist = s.artist
			it.Album = s.album
			it.URL = u
			it.Duration = s.duration
			it.Bitrate = s.bitrate
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

// songURL resolves the mp3 url of one rid via the classic anti.s endpoint.
func (k *Kuwo) songURL(ctx context.Context, rid string) (string, error) {
	q := url.Values{
		"type":     {"convert_url"},
		"format":   {"mp3"},
		"response": {"url"},
		"rid":      {"MUSIC_" + rid},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, kuwoURLURL+"?"+q.Encode(), nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", kuwoUA)
	resp, err := k.HTTP.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 8<<10))
	if err != nil {
		return "", err
	}
	u := strings.TrimSpace(string(body))
	if !strings.HasPrefix(u, "http") {
		return "", nil
	}
	return u, nil
}

var (
	// kuwo.cn returns a single-quoted pseudo-JSON; each song block contains
	// 'DC_TARGETID'. Field names differ from the documented API.
	kuwoRidRE   = regexp.MustCompile(`'DC_TARGETID':'?(\d+)'?`)
	kuwoFieldRE = map[string]*regexp.Regexp{
		"name":     regexp.MustCompile(`'SONGNAME':'([^']*)'`),
		"artist":   regexp.MustCompile(`'ARTIST':'([^']*)'`),
		"album":    regexp.MustCompile(`'ALBUM':'([^']*)'`),
		"formats":  regexp.MustCompile(`'FORMATS':'([^']*)'`),
		"minfo":    regexp.MustCompile(`'MINFO':'([^']*)'`),
		"duration": regexp.MustCompile(`'DURATION':'?(\d+)'?`),
	}
	kuwoBitrateRE = regexp.MustCompile(`(?i)bitrate:(\d+)`)
	kuwoFormatRE  = regexp.MustCompile(`^(MP3|AAC|WMA|FLAC|APE|OGG|MP4)(\d+)$`)
)

// parseKuwoSearch parses the single-quoted pseudo-JSON returned by
// search.kuwo.cn (rformat=json). Song blocks contain nested objects
// (e.g. 'audiobookpayinfo':{...}), so they are split on "},{" instead of
// relying on a brace-free regexp.
func parseKuwoSearch(body string) []kuwoSong {
	chunks := strings.Split(body, "},{")
	out := make([]kuwoSong, 0, len(chunks))
	for _, rec := range chunks {
		m := kuwoRidRE.FindStringSubmatch(rec)
		if m == nil {
			continue
		}
		s := kuwoSong{rid: m[1]}
		if mm := kuwoFieldRE["name"].FindStringSubmatch(rec); mm != nil {
			s.title = unescapeKuwo(mm[1])
		}
		if mm := kuwoFieldRE["artist"].FindStringSubmatch(rec); mm != nil {
			s.artist = unescapeKuwo(mm[1])
		}
		if mm := kuwoFieldRE["album"].FindStringSubmatch(rec); mm != nil {
			s.album = unescapeKuwo(mm[1])
		}
		if mm := kuwoFieldRE["formats"].FindStringSubmatch(rec); mm != nil {
			s.formats = mm[1]
		}
		if mm := kuwoFieldRE["minfo"].FindStringSubmatch(rec); mm != nil {
			s.minfo = mm[1]
		}
		if mm := kuwoFieldRE["duration"].FindStringSubmatch(rec); mm != nil {
			if n, err := strconv.Atoi(mm[1]); err == nil {
				s.duration = n * 1000
			}
		}
		s.bitrate = kuwoBitrate(s.formats, s.minfo)
		if s.title == "" {
			continue
		}
		out = append(out, s)
	}
	return out
}

// kuwoBitrate returns the highest bitrate advertised for a song. MINFO looks
// like "level:p,bitrate:320,format:mp3,size:3.24Mb;level:s,bitrate:48,...";
// FORMATS looks like "AAC48|MP3128|MP3H|WMA128" (MP3H == 320k, MP3128 ==
// 128k: the codec name and the bitrate are concatenated).
func kuwoBitrate(formats, minfo string) int {
	best := 0
	for _, m := range kuwoBitrateRE.FindAllStringSubmatch(minfo, -1) {
		if n, err := strconv.Atoi(m[1]); err == nil && n > best {
			best = n
		}
	}
	if best == 0 {
		for _, part := range strings.Split(formats, "|") {
			up := strings.ToUpper(strings.TrimSpace(part))
			if up == "MP3H" {
				if best < 320 {
					best = 320
				}
				continue
			}
			if m := kuwoFormatRE.FindStringSubmatch(up); m != nil {
				if n, err := strconv.Atoi(m[2]); err == nil && n > best {
					best = n
				}
			}
		}
	}
	if best == 0 {
		best = 128
	}
	if best > 512 { // "lossless" marker (e.g. bitrate:2000); the url we ask for is mp3
		best = 320
	}
	return best
}

func unescapeKuwo(s string) string {
	r := strings.NewReplacer(
		"&nbsp;", " ", "&amp;", "&", "&lt;", "<", "&gt;", ">", "&quot;", `"`, "&#39;", "'",
		`\\u0026`, "&", `\\u003c`, "<", `\\u003e`, ">",
	)
	return strings.TrimSpace(r.Replace(s))
}
