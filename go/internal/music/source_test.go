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

func TestParseKuwoSearch(t *testing.T) {
	body := `{'abslist':[{'AARTIST':'Cheer&nbsp;Chen','ALBUM':'Demo&nbsp;3','ARTIST':'陈绮贞','DC_TARGETID':'27826333','DURATION':'84','FORMATS':'AAC48|MP3128|MP3H','MINFO':'level:p,bitrate:320,format:mp3;level:h,bitrate:128,format:mp3','SONGNAME':'我喜欢木村拓哉','audiobookpayinfo':{'download':'0','play':'0'}},{'ALBUM':'x','ARTIST':'y','DC_TARGETID':123456,'DURATION':200,'FORMATS':'MP3128','SONGNAME':'另一首'}]}`
	songs := parseKuwoSearch(body)
	if len(songs) != 2 {
		t.Fatalf("parsed %d songs, want 2: %+v", len(songs), songs)
	}
	if songs[0].rid != "27826333" || songs[0].title != "我喜欢木村拓哉" {
		t.Fatalf("song0 = %+v", songs[0])
	}
	if songs[0].bitrate != 320 {
		t.Fatalf("bitrate = %d, want 320", songs[0].bitrate)
	}
	if songs[0].duration != 84000 {
		t.Fatalf("duration = %d, want 84000", songs[0].duration)
	}
	if songs[1].rid != "123456" || songs[1].bitrate != 128 {
		t.Fatalf("song1 = %+v", songs[1])
	}
}

func TestKuwoBitrate(t *testing.T) {
	cases := []struct {
		formats, minfo string
		want           int
	}{
		{"AAC48|MP3128|MP3H", "level:p,bitrate:320,format:mp3;level:h,bitrate:128", 320},
		{"MP3128|WMA96", "", 128},
		{"", "bitrate:2000,format:flac", 320}, // clamped: we request mp3
		{"", "", 128},
	}
	for _, c := range cases {
		if got := kuwoBitrate(c.formats, c.minfo); got != c.want {
			t.Fatalf("kuwoBitrate(%q,%q) = %d, want %d", c.formats, c.minfo, got, c.want)
		}
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
