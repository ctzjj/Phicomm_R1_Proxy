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
	"strings"
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
	f.SetTotal(len(list.Items()))
	f.SetItems(list.Items())
	return nil
}

// songURL resolves the direct mp3 url of one song.
func (n *Netease) songURL(ctx context.Context, id int64) (string, error) {
	payload := map[string]any{
		"method": "POST",
		"url":    "http://music.163.com/api/song/enhance/player/url",
		"params": map[string]any{
			"ids": []int64{id},
			"br":  320000,
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
