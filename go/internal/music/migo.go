package music

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

const migoSearchURL = "https://m.music.migu.cn/migu/remoting/scr_search_tag"

// Migo searches music on m.music.migu.cn.
type Migo struct {
	HTTP *http.Client
}

// NewMigo returns a Migo provider.
func NewMigo() *Migo {
	return &Migo{HTTP: &http.Client{Timeout: 12 * time.Second}}
}

type migoSong struct {
	AlbumName string `json:"albumName"`
	Title     string `json:"title"`
	Artist    string `json:"artist"`
	Cover     string `json:"cover"`
	Lyrics    string `json:"lyrics"`
	Mp3       string `json:"mp3"`
}

// Search fills f with the Migo results for keyword.
func (m *Migo) Search(ctx context.Context, keyword string, f *Format) error {
	const pageSize = 20
	q := url.Values{
		"keyword": {keyword},
		"type":    {"2"},
		"rows":    {strconv.Itoa(pageSize)},
		"pgc":     {"1"},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, migoSearchURL+"?"+q.Encode(), nil)
	if err != nil {
		return err
	}
	req.Host = "m.music.migu.cn"
	req.Header.Set("Referer", "https://m.music.migu.cn/v3/search")
	req.Header.Set("Accept", "application/json, text/javascript, */*; q=0.01")
	req.Header.Set("Accept-Language", "zh-CN,zh;q=0.9")
	req.Header.Set("User-Agent", "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1")

	resp, err := m.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("migo: http %d", resp.StatusCode)
	}
	var res struct {
		Musics []migoSong `json:"musics"`
	}
	if err := json.Unmarshal(body, &res); err != nil {
		return err
	}
	f.SetTotal(len(res.Musics))
	f.SetPageSize(pageSize)
	list := &ItemList{}
	for _, s := range res.Musics {
		it := NewItem()
		it.Album = s.AlbumName
		it.Title = s.Title
		it.Artist = s.Artist
		it.HdImgURL = s.Cover
		it.Lyric = s.Lyrics
		it.IsCollected = false
		it.URL = s.Mp3
		list.Add(it)
	}
	f.SetItems(list.Items())
	return nil
}
