package music

import (
	"testing"

	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/util"
)

func TestIsMusic(t *testing.T) {
	cases := []struct {
		name string
		body any
		want bool
		kw   string
	}{
		{
			name: "code SEARCH_ARTIST",
			body: map[string]any{"code": "SEARCH_ARTIST", "semantic": map[string]any{"intent": map[string]any{"keyword": "周杰伦"}}},
			want: true, kw: "周杰伦",
		},
		{
			name: "code SEARCH_CATEGORY",
			body: map[string]any{"code": "SEARCH_CATEGORY", "semantic": map[string]any{"intent": map[string]any{"keyword": "经典老歌"}}},
			want: true, kw: "经典老歌",
		},
		{
			name: "我想听X的歌 (ungreedy)",
			body: map[string]any{"text": "我想听周杰伦的歌"},
			want: true, kw: "周杰伦",
		},
		{
			name: "我想听X的Y",
			body: map[string]any{"text": "我想听周杰伦的稻香"},
			want: true, kw: "稻香 周杰伦",
		},
		{
			name: "播放X的Y",
			body: map[string]any{"text": "播放刘德华的忘情水"},
			want: true, kw: "忘情水 刘德华",
		},
		{
			name: "not music",
			body: map[string]any{"text": "今天天气怎么样"},
			want: false,
		},
		{
			name: "no body",
			body: nil,
			want: false,
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			p := New(&util.Data{Body: c.body})
			if got := p.IsMusic(); got != c.want {
				t.Fatalf("IsMusic() = %v, want %v", got, c.want)
			}
			if c.want && p.Keyword() != c.kw {
				t.Fatalf("keyword = %q, want %q", p.Keyword(), c.kw)
			}
		})
	}
}
