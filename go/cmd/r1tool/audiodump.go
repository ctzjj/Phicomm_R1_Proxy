package main

import (
	"bytes"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/audio"
)

// runAudioDump converts the request dump written by "r1tool asr -dump DIR"
// into per-utterance Ogg/Opus files (16 kHz mono), grouped by session id.
func runAudioDump(args []string) error {
	fs := flag.NewFlagSet("audiodump", flag.ExitOnError)
	dir := fs.String("dir", "", "dump directory produced by 'r1tool asr -dump'")
	out := fs.String("out", "", "output directory (default: <dir>/out)")
	minPkts := fs.Int("min", 5, "skip utterances with fewer packets")
	_ = fs.Parse(args)
	if *dir == "" {
		return fmt.Errorf("audiodump: -dir is required")
	}
	outDir := *out
	if outDir == "" {
		outDir = filepath.Join(*dir, "out")
	}

	entries, err := os.ReadDir(*dir)
	if err != nil {
		return err
	}
	names := make([]string, 0, len(entries))
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), "_req.bin") {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)

	type utt struct {
		sid   string
		pkts  [][]byte
		files int
	}
	bySID := map[string]*utt{}
	var order []string
	for _, name := range names {
		binPath := filepath.Join(*dir, name)
		hdrPath := strings.TrimSuffix(binPath, ".bin") + ".hdr"
		hdr, err := os.ReadFile(hdrPath)
		if err != nil {
			continue
		}
		if !bytes.Contains(hdr, []byte("/trafficRouter/cs")) {
			continue // only the streaming upload carries audio
		}
		sid := audio.SessionID(hdr)
		if sid == "" {
			sid = "unknown"
		}
		body, err := os.ReadFile(binPath)
		if err != nil {
			continue
		}
		pkts := audio.ParseChunks(body)
		if len(pkts) == 0 {
			continue
		}
		u := bySID[sid]
		if u == nil {
			u = &utt{sid: sid}
			bySID[sid] = u
			order = append(order, sid)
		}
		u.pkts = append(u.pkts, pkts...)
		u.files++
	}
	if len(order) == 0 {
		return fmt.Errorf("audiodump: no /trafficRouter/cs audio found in %s", *dir)
	}
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return err
	}
	var safeRE = regexp.MustCompile(`[^A-Za-z0-9_.-]`)
	for i, sid := range order {
		u := bySID[sid]
		if len(u.pkts) < *minPkts {
			continue
		}
		name := fmt.Sprintf("utt%d_%s.ogg", i+1, safeRE.ReplaceAllString(sid, "_"))
		if err := os.WriteFile(filepath.Join(outDir, name), audio.OggOpus(u.pkts), 0o644); err != nil {
			return err
		}
		log.Printf("[audiodump] %s: %d posts, %d packets, %.2fs -> %s",
			sid, u.files, len(u.pkts), float64(len(u.pkts))*0.02, name)
	}
	return nil
}
