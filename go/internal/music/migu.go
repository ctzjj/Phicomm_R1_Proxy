package music

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	miguSearchURL = "http://pd.musicapp.migu.cn/MIGUM2.0/v1.0/content/search_all.do"
	miguListenURL = "https://c.musicapp.migu.cn/MIGUM2.0/v2.1/content/listen-url"
	miguUA        = "Android_migu/7.41.13 okhttp/3.12.13"
	miguChannel   = "0146832"
	miguVersion   = "7.41.13"
)

// Migu searches music on music.migu.cn (咪咕).
//
// Search works anonymously; only the PQ (128 kbps) stream is available
// without a login (HQ/SQ/ZQ answer "登录后免费试听"), so the provider always
// asks for PQ.
type Migu struct {
	HTTP *http.Client
}

// NewMigu returns a Migu provider.
func NewMigu() *Migu {
	return &Migu{HTTP: &http.Client{Timeout: 12 * time.Second}}
}

// Name implements Source.
func (m *Migu) Name() string { return "migu" }

type miguSong struct {
	contentID string
	title     string
	artist    string
	album     string
	cover     string
}

type miguSearchResp struct {
	SongResultData struct {
		Result []struct {
			ContentID string `json:"contentId"`
			Name      string `json:"name"`
			Singers   []struct {
				Name string `json:"name"`
			} `json:"singers"`
			Albums []struct {
				Name string `json:"name"`
			} `json:"albums"`
			ImgItems []struct {
				Img string `json:"img"`
			} `json:"imgItems"`
		} `json:"result"`
	} `json:"songResultData"`
}

// Search returns up to limit playable Migu tracks.
func (m *Migu) Search(ctx context.Context, keyword string, limit int) ([]Item, error) {
	if limit <= 0 || limit > 30 {
		limit = 20
	}
	q := url.Values{}
	q.Set("ua", "Android_migu")
	q.Set("version", "5.0.1")
	q.Set("text", keyword)
	q.Set("pageNo", "1")
	q.Set("pageSize", strconv.Itoa(limit))
	q.Set("searchSwitch", `{"song":1,"album":0,"singer":0,"tagSong":0,"mvSong":0,"songlist":0,"bestShow":1}`)

	body, err := m.get(ctx, miguSearchURL+"?"+q.Encode())
	if err != nil {
		return nil, err
	}
	var resp miguSearchResp
	if err := json.Unmarshal(body, &resp); err != nil {
		return nil, fmt.Errorf("migu json: %w", err)
	}
	songs := make([]miguSong, 0, len(resp.SongResultData.Result))
	for _, s := range resp.SongResultData.Result {
		if s.ContentID == "" || s.Name == "" {
			continue
		}
		ms := miguSong{contentID: s.ContentID, title: s.Name}
		if len(s.Singers) > 0 {
			ms.artist = s.Singers[0].Name
		}
		if len(s.Albums) > 0 {
			ms.album = s.Albums[0].Name
		}
		if len(s.ImgItems) > 0 {
			ms.cover = s.ImgItems[0].Img
		}
		songs = append(songs, ms)
		if len(songs) >= limit {
			break
		}
	}

	items := make([]Item, len(songs))
	var wg sync.WaitGroup
	sem := make(chan struct{}, 4)
	for i, s := range songs {
		wg.Add(1)
		go func(i int, s miguSong) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			u, err := m.songURL(ctx, s.contentID)
			if err != nil || u == "" {
				return
			}
			it := NewItem()
			it.Title = s.title
			it.Artist = s.artist
			it.Album = s.album
			it.HdImgURL = s.cover
			it.URL = u
			it.Bitrate = 128 // PQ
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

// songURL resolves the PQ (128k) stream of one content id.
func (m *Migu) songURL(ctx context.Context, contentID string) (string, error) {
	q := url.Values{}
	q.Set("netType", "01")
	q.Set("resourceType", "2")
	q.Set("contentId", contentID)
	q.Set("toneFlag", "PQ")
	body, err := m.get(ctx, miguListenURL+"?"+q.Encode())
	if err != nil {
		return "", err
	}
	var resp struct {
		Code string `json:"code"`
		Info string `json:"info"`
		Data struct {
			URL string `json:"url"`
		} `json:"data"`
	}
	if err := json.Unmarshal(body, &resp); err != nil {
		return "", fmt.Errorf("migu listen json: %w", err)
	}
	if resp.Data.URL == "" {
		return "", fmt.Errorf("migu: no stream (%s)", strings.TrimSpace(resp.Info))
	}
	return resp.Data.URL, nil
}

func (m *Migu) get(ctx context.Context, u string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", miguUA)
	req.Header.Set("Referer", "https://music.migu.cn/")
	req.Header.Set("channel", miguChannel)
	req.Header.Set("version", miguVersion)
	resp, err := m.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("migu: http %d", resp.StatusCode)
	}
	return body, nil
}
