package music

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"
	"unicode"
)

// Source is one music provider (网易云 / 酷我 / ...).
type Source interface {
	Name() string
	Search(ctx context.Context, keyword string, limit int) ([]Item, error)
}

// DefaultSources returns the enabled providers.
func DefaultSources() []Source {
	return []Source{NewNetease(), NewKuwo()}
}

// SearchAll queries every source concurrently, merges the results and keeps
// the best-quality version of each song (same title+artist).
func SearchAll(ctx context.Context, keyword string, sources []Source, limit int) ([]Item, []error) {
	type result struct {
		name  string
		items []Item
		err   error
	}
	ch := make(chan result, len(sources))
	var wg sync.WaitGroup
	for _, s := range sources {
		wg.Add(1)
		go func(s Source) {
			defer wg.Done()
			sctx, cancel := context.WithTimeout(ctx, 8*time.Second)
			defer cancel()
			items, err := s.Search(sctx, keyword, limit)
			ch <- result{name: s.Name(), items: items, err: err}
		}(s)
	}
	wg.Wait()
	close(ch)

	var errs []error
	var all []Item
	for r := range ch {
		if r.err != nil {
			errs = append(errs, fmt.Errorf("%s: %w", r.name, r.err))
			continue
		}
		for i := range r.items {
			r.items[i].Origin = r.name
		}
		all = append(all, r.items...)
	}
	return Dedupe(all), errs
}

// Dedupe keeps one item per (title, artist), preferring higher quality.
func Dedupe(items []Item) []Item {
	index := make(map[string]int, len(items))
	var out []Item
	for _, it := range items {
		if it.URL == "" || it.Title == "" {
			continue
		}
		k := songKey(it)
		if i, ok := index[k]; ok {
			if better(it, out[i]) {
				out[i] = it
			}
			continue
		}
		index[k] = len(out)
		out = append(out, it)
	}
	return out
}

// better reports whether a is a higher quality version than b.
func better(a, b Item) bool {
	if a.Bitrate != b.Bitrate {
		return a.Bitrate > b.Bitrate
	}
	if a.Size != b.Size {
		return a.Size > b.Size
	}
	return sourceRank(a.Origin) > sourceRank(b.Origin)
}

// sourceRank prefers providers whose urls the R1 player starts reliably.
func sourceRank(origin string) int {
	switch origin {
	case "netease":
		return 3
	case "kuwo":
		return 2
	default:
		return 1
	}
}

// songKey normalises title+artist so the same song from different providers
// collapses into one entry.
func songKey(it Item) string {
	return norm(it.Title) + "|" + norm(it.Artist)
}

func norm(s string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(s) {
		switch {
		case unicode.IsLetter(r), unicode.IsDigit(r):
			b.WriteRune(r)
		}
	}
	return b.String()
}
