package music

import (
	"fmt"
	"math/rand"
	"time"
)

// AudioFormat mirrors the PHP class in src/Provider/Audio/Format.php: it
// decorates an existing ASR body with audio (Ximalaya style) search results.
// The verification proxy does not use it, but it is kept for completeness.
type AudioFormat struct {
	data map[string]any
}

// NewAudioFormat wraps the decoded ASR body.
func NewAudioFormat(data map[string]any) *AudioFormat {
	if data == nil {
		data = map[string]any{}
	}
	data["service"] = "cn.yunzhisheng.audio"
	data["history"] = "cn.yunzhisheng.audio"
	data["code"] = "SEARCH_CATEGORY"
	return &AudioFormat{data: data}
}

// SetSemantic replaces the semantic block.
func (f *AudioFormat) SetSemantic(sem map[string]any) *AudioFormat {
	f.data["semantic"] = sem
	return f
}

// SetOriginIntent replaces originIntent.
func (f *AudioFormat) SetOriginIntent(v any) *AudioFormat { f.data["originIntent"] = v; return f }

// SetUniCarRet replaces uniCarRet.
func (f *AudioFormat) SetUniCarRet(v any) *AudioFormat { f.data["uniCarRet"] = v; return f }

// SetKeyword sets the "playing for you" text.
func (f *AudioFormat) SetKeyword(keyword string) *AudioFormat {
	f.data["general"] = map[string]any{
		"actionAble": true,
		"quitDialog": true,
		"text":       fmt.Sprintf("为您播放%s", keyword),
		"type":       "T",
	}
	return f
}

// SetTotal sets data.result.total.
func (f *AudioFormat) SetTotal(total int) *AudioFormat {
	res := f.result()
	res["total"] = total
	return f
}

// SetPlaylist sets data.result.playlist.
func (f *AudioFormat) SetPlaylist(p *Playlist) *AudioFormat {
	if p == nil || len(p.items) == 0 {
		return f
	}
	f.result()["playlist"] = p.items
	return f
}

// Data returns the decorated body.
func (f *AudioFormat) Data() map[string]any { return f.data }

func (f *AudioFormat) result() map[string]any {
	data, ok := f.data["data"].(map[string]any)
	if !ok {
		data = map[string]any{}
		f.data["data"] = data
	}
	res, ok := data["result"].(map[string]any)
	if !ok {
		res = map[string]any{}
		data["result"] = res
	}
	return res
}

// Playlist collects audio entries.
type Playlist struct {
	items []map[string]any
}

// Add appends an item when it has a URL.
func (p *Playlist) Add(it *PlaylistItem) {
	if it == nil {
		return
	}
	if u, _ := it.item["url"].(string); u == "" {
		return
	}
	p.items = append(p.items, it.item)
}

// Items returns the collected entries.
func (p *Playlist) Items() []map[string]any { return p.items }

// PlaylistItem is one audio entry.
type PlaylistItem struct {
	item map[string]any
}

// NewPlaylistItem mirrors the PHP constructor (random placeholders).
func NewPlaylistItem() *PlaylistItem {
	return &PlaylistItem{item: map[string]any{
		"episode":     rand.Intn(9999) + 1,
		"play_count":  rand.Intn(9999) + 1,
		"tags":        "",
		"duration":    rand.Intn(9999) + 1,
		"update_time": time.Now().Format("2006-01-02 15:04:05"),
		"id":          rand.Intn(9999) + 1,
	}}
}

// SetURLM4aHigh sets url_m4a_high.
func (i *PlaylistItem) SetURLM4aHigh(v string) *PlaylistItem { i.item["url_m4a_high"] = v; return i }

// SetURLm4a sets urlm4a.
func (i *PlaylistItem) SetURLm4a(v string) *PlaylistItem { i.item["urlm4a"] = v; return i }

// SetTitle sets title.
func (i *PlaylistItem) SetTitle(v string) *PlaylistItem { i.item["title"] = v; return i }

// SetURL sets url.
func (i *PlaylistItem) SetURL(v string) *PlaylistItem { i.item["url"] = v; return i }

// SetCover sets cover.
func (i *PlaylistItem) SetCover(v string) *PlaylistItem { i.item["cover"] = v; return i }

// SetURLHigh sets url_high.
func (i *PlaylistItem) SetURLHigh(v string) *PlaylistItem { i.item["url_high"] = v; return i }

// SetCoverLarge sets cover_large.
func (i *PlaylistItem) SetCoverLarge(v string) *PlaylistItem { i.item["cover_large"] = v; return i }

// Map returns the entry.
func (i *PlaylistItem) Map() map[string]any { return i.item }
