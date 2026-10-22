package audio

import (
	"bytes"
	"encoding/binary"
	"testing"
)

func TestParseChunks(t *testing.T) {
	// two chunks: [len=3]"ABC" [len=2]"DE"
	body := []byte{3, 0, 'A', 'B', 'C', 2, 0, 'D', 'E'}
	p := ParseChunks(body)
	if len(p) != 2 || string(p[0]) != "ABC" || string(p[1]) != "DE" {
		t.Fatalf("unexpected packets %q", p)
	}
	// truncated tail must be ignored
	p = ParseChunks(append(body, 9, 0, 'X'))
	if len(p) != 2 {
		t.Fatalf("truncated chunk should be ignored, got %d", len(p))
	}
}

func TestSessionID(t *testing.T) {
	h := []byte("POST /trafficRouter/cs HTTP/1.1\r\nCRYP: 1\r\nP: drls.r.twirFsFhofriLG[ABC123]\r\n")
	if got := SessionID(h); got != "ABC123" {
		t.Fatalf("sid = %q", got)
	}
	if got := SessionID([]byte("POST /x HTTP/1.1\r\n\r\n")); got != "" {
		t.Fatalf("expected empty sid, got %q", got)
	}
}

func TestOggOpus(t *testing.T) {
	pkts := [][]byte{{0x48, 0x01, 1}, {0x48, 0x02, 2, 3}, {0x48, 0x00}}
	o := OggOpus(pkts)
	if !bytes.HasPrefix(o, []byte("OggS")) {
		t.Fatalf("missing OggS")
	}
	if !bytes.Contains(o, []byte("OpusHead")) || !bytes.Contains(o, []byte("OpusTags")) {
		t.Fatalf("missing opus headers")
	}
	// walk pages, verify CRC and last granule/EOS
	pages := 0
	var lastGranule uint64
	var lastFlags byte
	for i := 0; i+27 <= len(o); {
		if string(o[i:i+4]) != "OggS" {
			t.Fatalf("bad page magic at %d", i)
		}
		flags := o[i+5]
		gran := binary.LittleEndian.Uint64(o[i+6:])
		segs := int(o[i+26])
		v := make([]byte, 27+segs)
		copy(v, o[i:i+27+segs])
		bodyLen := 0
		for j := 0; j < segs; j++ {
			bodyLen += int(o[i+27+j])
		}
		page := make([]byte, 27+segs+bodyLen)
		copy(page, o[i:i+27+segs+bodyLen])
		want := binary.LittleEndian.Uint32(page[22:])
		page[22], page[23], page[24], page[25] = 0, 0, 0, 0
		if got := oggCRC(page); got != want {
			t.Fatalf("crc mismatch page %d: %08x != %08x", pages, got, want)
		}
		pages++
		lastGranule, lastFlags = gran, flags
		i += 27 + segs + bodyLen
	}
	if pages != 3 {
		t.Fatalf("pages = %d, want 3", pages)
	}
	if lastFlags != 0x04 {
		t.Fatalf("last page not EOS: %x", lastFlags)
	}
	if want := uint64(len(pkts) * PacketSamples48k); lastGranule != want {
		t.Fatalf("granule = %d, want %d", lastGranule, want)
	}
}
