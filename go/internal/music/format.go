// Package music re-implements the PHP music search PoC: detect a music
// intent in the ASR response and replace it with search results from a
// music provider (default: Netease).
package music

import "math/rand"

// Item is one entry of data.result.musicinfo.
type Item struct {
	ID          int    `json:"id"`
	ErrorCode   int    `json:"errorCode"`
	Duration    int    `json:"duration"`
	Lyric       string `json:"lyric"`
	Album       string `json:"album,omitempty"`
	Artist      string `json:"artist,omitempty"`
	HdImgURL    string `json:"hdImgUrl,omitempty"`
	ImgURL      string `json:"imgUrl,omitempty"`
	IsCollected bool   `json:"isCollected"`
	Title       string `json:"title,omitempty"`
	URL         string `json:"url,omitempty"`
}

// NewItem mirrors the PHP Item constructor (random id/duration placeholders;
// the speaker only uses url/title/artist).
func NewItem() *Item {
	return &Item{
		ID:        rand.Intn(9999999) + 1,
		Duration:  rand.Intn(9999999) + 1,
		ErrorCode: 0,
	}
}

// ItemList collects items, skipping entries without a playable URL, exactly
// like the PHP ItemList::setDataList().
type ItemList struct {
	items []Item
}

// Add appends item when it has a URL.
func (l *ItemList) Add(it *Item) {
	if it == nil || it.URL == "" {
		return
	}
	l.items = append(l.items, *it)
}

// Items returns the collected items.
func (l *ItemList) Items() []Item { return l.items }

// Result is data.result of the music response.
type Result struct {
	Count          int    `json:"count"`
	MusicInfo      []Item `json:"musicinfo"`
	TotalTime      int    `json:"totalTime"`
	PageSize       any    `json:"pagesize"`
	ErrorCode      int    `json:"errorCode"`
	Page           string `json:"page"`
	Source         int    `json:"source"`
	DataSourceName string `json:"dataSourceName"`
}

// Format is the response template sent back to the speaker.
type Format struct {
	Semantic any    `json:"semantic"`
	Code     string `json:"code"`
	Data     struct {
		Result Result `json:"result"`
	} `json:"data"`
	OriginIntent   any    `json:"originIntent"`
	History        string `json:"history"`
	Source         string `json:"source"`
	UniCarRet      any    `json:"uniCarRet"`
	AsrRecognize   string `json:"asr_recongize"`
	RC             int    `json:"rc"`
	General        any    `json:"general"`
	ReturnCode     int    `json:"returnCode"`
	AudioURL       string `json:"audioUrl,omitempty"`
	RetTag         string `json:"retTag"`
	Service        string `json:"service"`
	NluProcessTime string `json:"nluProcessTime"`
	Text           string `json:"text"`
	ResponseID     string `json:"responseId"`
}

// NewFormat returns the template used by the PHP Music\Format class.
func NewFormat() *Format {
	f := &Format{
		Code:    "SEARCH_CATEGORY",
		History: "cn.yunzhisheng.music",
		Source:  "nlu",
		// asr_recongize / general.text are replaced by SetAsrText.
		AsrRecognize:   "播放。",
		RC:             0,
		General:        map[string]any{"actionAble": "true", "quitDialog": "true", "text": "为您播放", "type": "T"},
		ReturnCode:     0,
		AudioURL:       "", // no stale TTS URL: let the local TTS announce, otherwise the player stays paused
		RetTag:         "nlu",
		Service:        "cn.yunzhisheng.music",
		NluProcessTime: "106",
		Text:           "为您播放",
		ResponseID:     "e490d9576c5b438c8283a6e71cdba997",
		OriginIntent:   map[string]any{"nluSlotInfos": []any{}},
		UniCarRet:      map[string]any{"result": map[string]any{}, "returnCode": 609, "message": "aios-home.hivoice.cn"},
		Semantic: map[string]any{
			"intent": map[string]any{"language": "zh", "tag": "", "keyword": ""},
		},
	}
	f.Data.Result = Result{
		Count:          0,
		MusicInfo:      []Item{},
		TotalTime:      10,
		PageSize:       "60",
		ErrorCode:      0,
		Page:           "1",
		Source:         1,
		DataSourceName: "我的音乐",
	}
	return f
}

// SetSemantic replaces the semantic block with the one from the ASR response.
func (f *Format) SetSemantic(sem any) *Format { f.Semantic = sem; return f }

// SetText sets the echoed text.
func (f *Format) SetText(text string) *Format { f.Text = text; return f }

// SetAsrText sets both general.text and asr_recongize.
func (f *Format) SetAsrText(text string) *Format {
	f.AsrRecognize = text
	if g, ok := f.General.(map[string]any); ok {
		g["text"] = text
	}
	return f
}

// SetTotal sets data.result.count.
func (f *Format) SetTotal(total int) *Format { f.Data.Result.Count = total; return f }

// SetPageSize sets data.result.pagesize.
func (f *Format) SetPageSize(size any) *Format { f.Data.Result.PageSize = size; return f }

// SetItems replaces data.result.musicinfo.
func (f *Format) SetItems(items []Item) *Format {
	if len(items) == 0 {
		return f
	}
	f.Data.Result.MusicInfo = items
	return f
}
