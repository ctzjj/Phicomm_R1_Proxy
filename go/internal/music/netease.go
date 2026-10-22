package music

import (
	"context"
	"crypto/aes"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	// Netease uses the same linux/forward API as the PHP implementation.
	neteaseForwardURL = "http://music.163.com/api/linux/forward"
	neteaseKeyHex     = "7246674226682325323F5E6544673A51"
	neteaseUA         = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.106 Safari/537.36"
)

// Netease searches music on music.163.com.
type Netease struct {
	HTTP     *http.Client
	Endpoint string
}

// NewNetease returns a Netease provider.
func NewNetease() *Netease {
	return &Netease{
		HTTP:     &http.Client{Timeout: 12 * time.Second},
		Endpoint: neteaseForwardURL,
	}
}

type neteaseSong struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
	Ar   []struct {
		Name string `json:"name"`
	} `json:"ar"`
	Al struct {
		Name   string `json:"name"`
		PicURL string `json:"picUrl"`
	} `json:"al"`
	Privilege struct {
		Fl int `json:"fl"`
	} `json:"privilege"`
}

type neteaseSearchResult struct {
	Result struct {
		Songs []neteaseSong `json:"songs"`
	} `json:"result"`
}

// Search fills f with up to 20 Netease results for keyword.
func (n *Netease) Search(ctx context.Context, keyword string, f *Format) error {
	const pageSize = 20
	payload := map[string]any{
		"method": "POST",
		"url":    "http://music.163.com/api/cloudsearch/pc",
		"params": map[string]any{
			"s":      keyword,
			"type":   "1",
			"offset": "0",
			"limit":  pageSize,
		},
	}
	var res neteaseSearchResult
	if err := n.call(ctx, payload, &res); err != nil {
		return err
	}
	f.SetPageSize(pageSize)

	list := &ItemList{}
	for _, s := range res.Result.Songs {
		if s.Privilege.Fl == 0 { // no copyright / not playable
			continue
		}
		u, err := n.songURL(ctx, s.ID)
		if err != nil || u == "" {
			continue
		}
		it := NewItem()
		it.Album = s.Al.Name
		it.Title = s.Name
		if len(s.Ar) > 0 {
			it.Artist = s.Ar[0].Name
		}
		it.HdImgURL = s.Al.PicURL
		it.Lyric = ""
		it.IsCollected = false
		it.URL = u
		list.Add(it)
	}
	// The speaker starts playback only when the first track prepares quickly,
	// so probe the urls and put the fastest reachable one first.
	items := ProbeOrder(ctx, list.Items())
	f.SetTotal(len(items))
	f.SetItems(items)
	return nil
}

// ProbeOrder HEADs every url concurrently and returns the reachable ones
// ordered so that the speaker can start playback reliably:
//  1. urls served by a plain nginx CDN (the R1 MediaPlayer chokes on some
//     object-store responses such as openresty's Content-Disposition/x-nos-*
//     headers -> the track prepares but never starts)
//  2. fastest first
// When nothing is reachable the input order is kept.
func ProbeOrder(ctx context.Context, items []Item) []Item {
	type res struct {
		it     Item
		d      time.Duration
		ok     bool
		plain  bool
		length bool
	}
	ch := make(chan res, len(items))
	var wg sync.WaitGroup
	for _, it := range items {
		wg.Add(1)
		go func(it Item) {
			defer wg.Done()
			req, err := http.NewRequestWithContext(ctx, http.MethodHead, it.URL, nil)
			if err != nil {
				ch <- res{it: it}
				return
			}
			req.Header.Set("Range", "bytes=0-0")
			cl := &http.Client{Timeout: 1500 * time.Millisecond}
			t0 := time.Now()
			resp, err := cl.Do(req)
			if err != nil {
				ch <- res{it: it}
				return
			}
			_ = resp.Body.Close()
			srv := strings.ToLower(resp.Header.Get("Server"))
			ct := strings.ToLower(resp.Header.Get("Content-Type"))
			plain := !strings.Contains(srv, "openresty") &&
				resp.Header.Get("Content-Disposition") == ""
			ch <- res{
				it:     it,
				d:      time.Since(t0),
				ok:     (resp.StatusCode == 200 || resp.StatusCode == 206) && strings.HasPrefix(ct, "audio/"),
				plain:  plain,
				length: resp.ContentLength > 0,
			}
		}(it)
	}
	wg.Wait()
	close(ch)

	var good []res
	for r := range ch {
		if r.ok && r.length {
			good = append(good, r)
		}
	}
	if len(good) == 0 {
		return items
	}
	hasPlain := false
	for _, r := range good {
		if r.plain {
			hasPlain = true
			break
		}
	}
	sort.Slice(good, func(i, j int) bool {
		if good[i].plain != good[j].plain {
			return good[i].plain
		}
		return good[i].d < good[j].d
	})
	out := make([]Item, 0, len(good))
	for _, r := range good {
		if hasPlain && !r.plain {
			continue // prefer urls the R1 player can actually start
		}
		out = append(out, r.it)
	}
	if len(out) > 10 {
		out = out[:10]
	}
	return out
}

// songURL resolves the direct mp3 url of one song.
func (n *Netease) songURL(ctx context.Context, id int64) (string, error) {
	payload := map[string]any{
		"method": "POST",
		"url":    "http://music.163.com/api/song/enhance/player/url",
		"params": map[string]any{
			"ids": []int64{id},
			"br":  128000,
		},
	}
	var res struct {
		Data []struct {
			URL string `json:"url"`
		} `json:"data"`
	}
	if err := n.call(ctx, payload, &res); err != nil {
		return "", err
	}
	if len(res.Data) == 0 {
		return "", errors.New("no url")
	}
	return res.Data[0].URL, nil
}

// call posts an encrypted eparams request and decodes the JSON reply into out.
func (n *Netease) call(ctx context.Context, payload any, out any) error {
	eparams, err := encryptEParams(payload)
	if err != nil {
		return err
	}
	form := url.Values{"eparams": {eparams}}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, n.Endpoint, strings.NewReader(form.Encode()))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Referer", "http://music.163.com/")
	req.Header.Set("User-Agent", neteaseUA)

	resp, err := n.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("netease: http %d", resp.StatusCode)
	}
	return json.Unmarshal(body, out)
}

// encryptEParams implements the PHP buildParam(): json_encode -> AES-128-ECB
// (PKCS#7) -> lowercase hex -> upper case.
func encryptEParams(v any) (string, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return "", err
	}
	key, err := hex.DecodeString(neteaseKeyHex)
	if err != nil {
		return "", err
	}
	enc, err := encryptECB(raw, key)
	if err != nil {
		return "", err
	}
	return strings.ToUpper(hex.EncodeToString(enc)), nil
}

// encryptECB encrypts plain with AES in ECB mode using PKCS#7 padding.
func encryptECB(plain, key []byte) ([]byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	bs := block.BlockSize()
	pad := bs - len(plain)%bs
	buf := make([]byte, len(plain)+pad)
	copy(buf, plain)
	for i := len(plain); i < len(buf); i++ {
		buf[i] = byte(pad)
	}
	out := make([]byte, len(buf))
	for i := 0; i < len(buf); i += bs {
		block.Encrypt(out[i:i+bs], buf[i:i+bs])
	}
	return out, nil
}
