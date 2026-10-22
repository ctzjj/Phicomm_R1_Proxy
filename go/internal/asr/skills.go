package asr

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"
)

// SkillMatch selects which utterances a skill handles.
type SkillMatch struct {
	Type    string `json:"type"`    // chat | command | keyword | code | any
	Pattern string `json:"pattern"` // regexp for keyword
	Value   string `json:"value"`   // code value for code
}

// SkillAction is what happens when a skill matches.
type SkillAction struct {
	Type      string `json:"type"`      // builtin | llm | http
	URL       string `json:"url"`       // endpoint for llm/http
	Method    string `json:"method"`    // http method (default POST)
	Key       string `json:"key"`       // optional api key
	KeyHeader string `json:"keyHeader"` // header for the key (default Authorization)
	Body      string `json:"body"`      // http body template: {{text}} {{asr}} {{sid}}
	Reply     string `json:"reply"`     // text spoken after a successful http call
}

// Skill is one routing rule. The first enabled match wins.
type Skill struct {
	Name    string      `json:"name"`
	Enabled *bool       `json:"enabled"`
	Match   SkillMatch  `json:"match"`
	Action  SkillAction `json:"action"`
}

func (s Skill) isEnabled() bool { return s.Enabled == nil || *s.Enabled }

// matchSkill returns the first skill matching the cloud NLU result.
func matchSkill(skills []Skill, code, text string) *Skill {
	for i := range skills {
		s := &skills[i]
		if !s.isEnabled() {
			continue
		}
		switch strings.ToLower(strings.TrimSpace(s.Match.Type)) {
		case "any":
			return s
		case "chat":
			if code == "" || strings.EqualFold(code, "ANSWER") {
				return s
			}
		case "command":
			if code != "" && !strings.EqualFold(code, "ANSWER") {
				return s
			}
		case "code":
			if strings.EqualFold(code, strings.TrimSpace(s.Match.Value)) {
				return s
			}
		case "keyword":
			if s.Match.Pattern == "" {
				continue
			}
			if re, err := regexp.Compile(s.Match.Pattern); err == nil && re.MatchString(text) {
				return s
			}
		}
	}
	return nil
}

// cloudFields extracts the intent code and the recognised text from the cloud
// NLU body.
func cloudFields(body any) (code, text string) {
	m, ok := body.(map[string]any)
	if !ok {
		return "", ""
	}
	if v, ok := m["code"].(string); ok {
		code = v
	}
	for _, key := range []string{"asr_recongize", "text"} {
		if v, ok := m[key].(string); ok && v != "" {
			text = v
			break
		}
	}
	if text == "" {
		if g, ok := m["general"].(map[string]any); ok {
			if v, ok := g["text"].(string); ok {
				text = v
			}
		}
	}
	return code, text
}

var skillClient = &http.Client{Timeout: 15 * time.Second}

// runSkill executes a matched skill. handled=false means "keep the built-in
// behaviour" (action type builtin).
func runSkill(sk Skill, sid, code, text string) (out []byte, handled bool) {
	switch strings.ToLower(strings.TrimSpace(sk.Action.Type)) {
	case "", "builtin":
		return nil, false
	case "llm":
		reply, obj, err := callJSONSkill(sk, sid, code, text)
		if err != nil {
			return nil, false // fall back to the cloud answer
		}
		if obj != nil {
			return nluResponse(sid, obj), true
		}
		return answerResponse(sid, reply, text), true
	case "http":
		reply, err := callHTTPSkill(sk, sid, code, text)
		if err != nil {
			return nil, false
		}
		if reply == "" {
			reply = sk.Action.Reply
		}
		if reply == "" {
			reply = "好的"
		}
		return answerResponse(sid, reply, text), true
	}
	return nil, false
}

// callJSONSkill posts {"text","sid","code"} to the endpoint and understands
// {"text"|"reply"} or a full speaker JSON (with "code") in the answer.
func callJSONSkill(sk Skill, sid, code, text string) (string, []byte, error) {
	payload, _ := json.Marshal(map[string]string{"text": text, "sid": sid, "code": code})
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, sk.Action.URL, bytes.NewReader(payload))
	if err != nil {
		return "", nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	setSkillKey(req, sk.Action)
	resp, err := skillClient.Do(req)
	if err != nil {
		return "", nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return "", nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return "", nil, fmt.Errorf("skill %s: http %d", sk.Name, resp.StatusCode)
	}
	trimmed := bytes.TrimSpace(body)
	if len(trimmed) > 0 && trimmed[0] == '{' {
		var m map[string]any
		if json.Unmarshal(trimmed, &m) == nil {
			if _, ok := m["code"]; ok {
				return "", trimmed, nil // already a speaker answer
			}
			for _, key := range []string{"text", "reply", "answer"} {
				if v, ok := m[key].(string); ok {
					return v, nil, nil
				}
			}
		}
	}
	return strings.TrimSpace(string(trimmed)), nil, nil
}

// callHTTPSkill performs a configurable HTTP request (e.g. smart-home API).
func callHTTPSkill(sk Skill, sid, code, text string) (string, error) {
	method := strings.ToUpper(strings.TrimSpace(sk.Action.Method))
	if method == "" {
		method = http.MethodPost
	}
	body := sk.Action.Body
	body = strings.ReplaceAll(body, "{{text}}", text)
	body = strings.ReplaceAll(body, "{{asr}}", text)
	body = strings.ReplaceAll(body, "{{sid}}", sid)
	body = strings.ReplaceAll(body, "{{code}}", code)
	var rdr io.Reader
	if body != "" {
		rdr = strings.NewReader(body)
	}
	req, err := http.NewRequestWithContext(context.Background(), method, sk.Action.URL, rdr)
	if err != nil {
		return "", err
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	setSkillKey(req, sk.Action)
	resp, err := skillClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	out, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("skill %s: http %d", sk.Name, resp.StatusCode)
	}
	return strings.TrimSpace(string(out)), nil
}

func setSkillKey(req *http.Request, a SkillAction) {
	key := strings.TrimSpace(a.Key)
	if key == "" {
		return
	}
	h := a.KeyHeader
	if h == "" {
		h = "Authorization"
	}
	if strings.EqualFold(h, "Authorization") && !strings.HasPrefix(strings.ToLower(key), "bearer ") {
		key = "Bearer " + key
	}
	req.Header.Set(h, key)
}

// answerResponse builds a speaker answer that just speaks text.
func answerResponse(sid, text, asrText string) []byte {
	obj := map[string]any{
		"code":          "ANSWER",
		"general":       map[string]any{"text": text, "type": "T"},
		"asr_recongize": asrText,
	}
	payload, _ := json.Marshal(obj)
	var b strings.Builder
	b.WriteString("HTTP/1.1 200 OK\r\nCT: W510\r\nRS: GeLdJ\r\nPN: ry\r\n")
	if sid != "" {
		fmt.Fprintf(&b, "SID: %s\r\n", sid)
	}
	b.WriteString("Content-Type: application/json\r\n")
	fmt.Fprintf(&b, "Content-Length: %d\r\n", len(payload))
	b.WriteString("Connection: keep-alive\r\n\r\n")
	b.Write(payload)
	return []byte(b.String())
}
