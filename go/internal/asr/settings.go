package asr

import "sync"

// Settings is the runtime configuration data (plain, JSON friendly).
type Settings struct {
	Upstream     string  `json:"upstream"`     // real ASR server host:port ("" = resolve asrv3 via DNS)
	DNS          string  `json:"dns"`          // DNS server used to resolve asrv3.hivoice.cn (default 223.5.5.5:53)
	MediaBase    string  `json:"mediaBase"`    // e.g. http://aios-home.hivoice.cn:8080
	Music        bool    `json:"music"`        // replace music intents with our search
	Forward      string  `json:"forward"`      // POST each utterance Ogg to this URL
	NLUMode      string  `json:"nluMode"`      // "default" (cloud) or "custom"
	NLUURL       string  `json:"nluUrl"`       // custom NLU endpoint
	NLUKey       string  `json:"nluKey"`       // optional api key
	NLUKeyHeader string  `json:"nluKeyHeader"` // header carrying the key (default Authorization)
	Skills       []Skill `json:"skills"`       // routing rules (see internal/asr/skills.go)
	AudioDir     string  `json:"audioDir"`     // where utterance .ogg files are written
	DumpDir      string  `json:"dumpDir"`      // raw request/response dump directory
}

// Snapshot is an immutable copy used per request.
type Snapshot struct {
	Upstream     string
	DNS          string
	MediaBase    string
	Music        bool
	Forward      string
	NLUMode      string
	NLUURL       string
	NLUKey       string
	NLUKeyHeader string
	Skills       []Skill
	AudioDir     string
	DumpDir      string
}

// Store holds the current settings and lets the web console change them while
// the proxy is running.
type Store struct {
	mu  sync.RWMutex
	cur Settings
}

// NewStore returns a store seeded with defaults.
func NewStore(s Settings) *Store {
	s = normalize(s)
	return &Store{cur: s}
}

func normalize(s Settings) Settings {
	s.NLUMode = NormalizeNLUMode(s.NLUMode)
	if s.NLUKeyHeader == "" {
		s.NLUKeyHeader = "Authorization"
	}
	return s
}

// Snapshot returns a consistent copy for one request.
func (st *Store) Snapshot() Snapshot {
	cur := st.Get()
	return Snapshot{
		Upstream:     cur.Upstream,
		DNS:          cur.DNS,
		MediaBase:    cur.MediaBase,
		Music:        cur.Music,
		Forward:      cur.Forward,
		NLUMode:      cur.NLUMode,
		NLUURL:       cur.NLUURL,
		NLUKey:       cur.NLUKey,
		NLUKeyHeader: cur.NLUKeyHeader,
		Skills:       append([]Skill(nil), cur.Skills...),
		AudioDir:     cur.AudioDir,
		DumpDir:      cur.DumpDir,
	}
}

// Get returns the current settings.
func (st *Store) Get() Settings {
	st.mu.RLock()
	defer st.mu.RUnlock()
	return st.cur
}

// Update applies the provided fields (empty strings keep the current value,
// except for the music toggle which always wins) and returns the new state.
func (st *Store) Update(in Settings) Settings {
	st.mu.Lock()
	defer st.mu.Unlock()
	cur := st.cur
	if in.Upstream != "" {
		cur.Upstream = in.Upstream
	}
	if in.DNS != "" {
		cur.DNS = in.DNS
	}
	if in.MediaBase != "" {
		cur.MediaBase = in.MediaBase
	}
	cur.Music = in.Music
	if in.Forward != "" {
		cur.Forward = in.Forward
	}
	if in.NLUMode != "" {
		cur.NLUMode = NormalizeNLUMode(in.NLUMode)
	}
	if in.NLUURL != "" {
		cur.NLUURL = in.NLUURL
	}
	if in.NLUKey != "" {
		cur.NLUKey = in.NLUKey
	}
	if in.NLUKeyHeader != "" {
		cur.NLUKeyHeader = in.NLUKeyHeader
	}
	cur.Skills = in.Skills
	if in.AudioDir != "" {
		cur.AudioDir = in.AudioDir
	}
	if in.DumpDir != "" {
		cur.DumpDir = in.DumpDir
	}
	st.cur = cur
	return cur
}

// NormalizeNLUMode maps the accepted spellings to "default" or "custom".
func NormalizeNLUMode(mode string) string {
	switch mode {
	case "custom", "external":
		return "custom"
	default:
		return "default"
	}
}
