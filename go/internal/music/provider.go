package music

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/util"
)

// Provider inspects an ASR response and, when it is a music request,
// replaces the response body with search results.
type Provider struct {
	data    *util.Data
	keyword string
}

// New returns a Provider for one ASR response.
func New(data *util.Data) *Provider { return &Provider{data: data} }

// Keyword returns the keyword detected by IsMusic.
func (p *Provider) Keyword() string { return p.keyword }

// musicPatterns mirrors MusicProvider::isMusic() (PCRE `#...#isuU` etc.).
// The first rule is ungreedy (`U`), the other two are not.
var musicPatterns = []struct {
	re   *regexp.Regexp
	pick func(m []string) string
}{
	{regexp.MustCompile(`(?isU)^我想听(.*)的歌$`), func(m []string) string { return m[1] }},
	{regexp.MustCompile(`(?is)^我想听(.*?)的(.*)`), func(m []string) string { return m[2] + " " + m[1] }},
	{regexp.MustCompile(`(?is)^播放(.*?)的(.*)`), func(m []string) string { return m[2] + " " + m[1] }},
}

// IsMusic reports whether the response is a music search request and, if so,
// stores the extracted keyword.
func (p *Provider) IsMusic() bool {
	body, ok := p.data.Body.(map[string]any)
	if !ok || body == nil {
		return false
	}
	code, _ := body["code"].(string)
	if code == "SEARCH_ARTIST" || code == "SEARCH_CATEGORY" {
		if kw := util.GetString(body, "semantic", "intent", "keyword"); kw != "" {
			p.keyword = kw
			return true
		}
	}
	text, _ := body["text"].(string)
	if text == "" {
		return false
	}
	for _, pat := range musicPatterns {
		if m := pat.re.FindStringSubmatch(text); m != nil {
			p.keyword = strings.TrimSpace(pat.pick(m))
			return p.keyword != ""
		}
	}
	return false
}

// Search queries all enabled sources concurrently, keeps the best-quality
// version of every song, verifies the urls and stores the formatted response
// in the Data body.
func (p *Provider) Search(ctx context.Context) error {
	body, _ := p.data.Body.(map[string]any)
	f := NewFormat()
	if body != nil {
		if sem, ok := body["semantic"]; ok {
			f.SetSemantic(sem)
		}
	}
	f.SetText(p.keyword)
	f.SetAsrText(p.keyword)
	f.SetPageSize(20)

	items, errs := SearchAll(ctx, p.keyword, DefaultSources(), 20)
	if len(errs) > 0 && len(items) == 0 {
		p.data.Body = f // keep the template so the speaker still gets a valid answer
		return errs[0]
	}
	items = ProbeOrder(ctx, items)
	if len(items) == 0 {
		p.data.Body = f
		return fmt.Errorf("music: no playable track for %q", p.keyword)
	}
	f.SetTotal(len(items))
	f.SetItems(items)
	p.data.Body = f
	return nil
}
