package music

import "testing"

func TestDedupeKeepsBestQuality(t *testing.T) {
	items := []Item{
		{Title: "旅行的意义", Artist: "陈绮贞", URL: "kuwo-128", Bitrate: 128, Origin: "kuwo"},
		{Title: "旅行的意义 ", Artist: "陈绮贞", URL: "ne-320", Bitrate: 320, Origin: "netease"},
		{Title: "旅行的意义 (Live)", Artist: "陈绮贞", URL: "live", Bitrate: 320, Origin: "netease"},
		{Title: "", Artist: "x", URL: "bad"},
	}
	out := Dedupe(items)
	if len(out) != 2 {
		t.Fatalf("dedupe = %d items, want 2: %+v", len(out), out)
	}
	if out[0].URL != "ne-320" {
		t.Fatalf("kept %q, want the 320k version", out[0].URL)
	}
}

func TestParseKuwoSearchJSON(t *testing.T) {
	body := []byte(`{"abslist":[
		{"MUSICRID":"MUSIC_27826333","SONGNAME":"我喜欢木村拓哉","ARTIST":"陈绮贞","ALBUM":"Demo 3","DURATION":"84","MINFO":"level:p,bitrate:320,format:mp3","bitSwitch":1},
		{"MUSICRID":"MUSIC_123456","SONGNAME":"另一首","ARTIST":"y","ALBUM":"x","DURATION":200,"bitSwitch":1},
		{"MUSICRID":"MUSIC_999","SONGNAME":"无版权","ARTIST":"z","bitSwitch":0}
	]}`)
	songs, err := parseKuwoSearchJSON(body)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(songs) != 2 {
		t.Fatalf("parsed %d songs, want 2 (bitSwitch=0 skipped): %+v", len(songs), songs)
	}
	if songs[0].rid != "27826333" || songs[0].title != "我喜欢木村拓哉" || songs[0].duration != 84 {
		t.Fatalf("song0 = %+v", songs[0])
	}
	if songs[1].rid != "123456" || songs[1].duration != 200 {
		t.Fatalf("song1 = %+v", songs[1])
	}
}

func TestLooksLikeAudio(t *testing.T) {
	if !looksLikeAudio([]byte{0x49, 0x44, 0x33, 0x04}) { // ID3
		t.Fatal("ID3 not recognised")
	}
	if !looksLikeAudio([]byte{0xFF, 0xFB, 0x90, 0x00}) { // mp3 frame
		t.Fatal("mp3 frame not recognised")
	}
	if looksLikeAudio([]byte("<html>")) {
		t.Fatal("html accepted as audio")
	}
}

func TestContentRangeTotal(t *testing.T) {
	if got := contentRangeTotal("bytes 0-2047/9771036"); got != 9771036 {
		t.Fatalf("total = %d", got)
	}
	if got := contentRangeTotal(""); got != 0 {
		t.Fatalf("empty total = %d", got)
	}
}
