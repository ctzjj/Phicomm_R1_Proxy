// Package audio understands the audio upload format of the Yunzhisheng
// client (libuscasr) used by the R1 speaker: each POST /trafficRouter/cs
// body is a sequence of [uint16 LE length][Opus packet] chunks (16 kHz mono,
// SILK WB, 20 ms per packet, TOC 0x48). The packets are plain Opus; the
// "CRYP: 1" header only obfuscates the metadata headers.
//
// This package parses the chunks, groups them per session (the P header
// carries the session id) and muxes them into a standard Ogg/Opus stream so
// the audio can be handed to any downstream ASR/LLM without pulling an Opus
// decoder into the proxy.
package audio

import (
	"encoding/binary"
	"regexp"
)

// PacketSamples48k is the number of 48 kHz samples in one 20 ms packet.
const PacketSamples48k = 960

// Preskip is the standard Opus pre-skip (48 kHz samples).
const Preskip = 312

var sidRE = regexp.MustCompile(`(?mi)^P:[^\r\n]*\[([^\]\r\n]+)\]`)

// SessionID extracts the session id from the request headers ("P:" line).
func SessionID(header []byte) string {
	m := sidRE.FindSubmatch(header)
	if m == nil {
		return ""
	}
	return string(m[1])
}

// ParseChunks splits a request body into Opus packets.
func ParseChunks(b []byte) [][]byte {
	var out [][]byte
	for i := 0; i+2 <= len(b); {
		n := int(binary.LittleEndian.Uint16(b[i:]))
		if n == 0 || i+2+n > len(b) {
			break
		}
		pkt := make([]byte, n)
		copy(pkt, b[i+2:i+2+n])
		out = append(out, pkt)
		i += 2 + n
	}
	return out
}

// OggOpus muxes 16 kHz mono Opus packets into an Ogg/Opus stream.
func OggOpus(packets [][]byte) []byte {
	var out []byte
	serial := uint32(0x52314F50) // "R1OP"
	seq := uint32(0)

	head := make([]byte, 0, 19)
	head = append(head, "OpusHead"...)
	head = append(head, 1)                                 // version
	head = append(head, 1)                                 // channels
	head = binary.LittleEndian.AppendUint16(head, Preskip) // pre-skip
	head = binary.LittleEndian.AppendUint32(head, 16000)   // input sample rate
	head = binary.LittleEndian.AppendUint16(head, 0)       // output gain
	head = append(head, 0)                                 // mapping family
	out = append(out, oggPage(serial, seq, 0x02, 0, [][]byte{head})...)
	seq++

	vendor := []byte("r1tool")
	tags := make([]byte, 0, 16+len(vendor))
	tags = append(tags, "OpusTags"...)
	tags = binary.LittleEndian.AppendUint32(tags, uint32(len(vendor)))
	tags = append(tags, vendor...)
	tags = binary.LittleEndian.AppendUint32(tags, 0) // no comments
	out = append(out, oggPage(serial, seq, 0, 0, [][]byte{tags})...)
	seq++

	// Audio pages: keep at most 250 packets (lacing values) per page.
	done := 0
	for i := 0; i < len(packets); i += 250 {
		end := i + 250
		if end > len(packets) {
			end = len(packets)
		}
		done = end
		flags := byte(0)
		if end == len(packets) {
			flags = 0x04 // EOS
		}
		granule := int64(done) * PacketSamples48k
		out = append(out, oggPage(serial, seq, flags, granule, packets[i:end])...)
		seq++
	}
	return out
}

// oggPage builds one Ogg page (CRC over the page with the CRC field zeroed).
func oggPage(serial, seq uint32, flags byte, granule int64, packets [][]byte) []byte {
	var segs []byte
	var data []byte
	for _, p := range packets {
		n := len(p)
		for n >= 255 {
			segs = append(segs, 255)
			n -= 255
		}
		segs = append(segs, byte(n))
		data = append(data, p...)
	}
	if len(segs) > 255 {
		segs = segs[:255]
	}
	h := make([]byte, 27+len(segs)+len(data))
	copy(h, "OggS")
	h[4] = 0
	h[5] = flags
	binary.LittleEndian.PutUint64(h[6:], uint64(granule))
	binary.LittleEndian.PutUint32(h[14:], serial)
	binary.LittleEndian.PutUint32(h[18:], seq)
	// bytes 22..25 = CRC (zero for now)
	h[26] = byte(len(segs))
	copy(h[27:], segs)
	copy(h[27+len(segs):], data)
	binary.LittleEndian.PutUint32(h[22:], oggCRC(h))
	return h
}

var crcTable [256]uint32

func init() {
	for i := 0; i < 256; i++ {
		r := uint32(i) << 24
		for j := 0; j < 8; j++ {
			if r&0x80000000 != 0 {
				r = (r << 1) ^ 0x04c11db7
			} else {
				r <<= 1
			}
		}
		crcTable[i] = r
	}
}

func oggCRC(b []byte) uint32 {
	var crc uint32
	for _, c := range b {
		crc = (crc << 8) ^ crcTable[byte(crc>>24)^c]
	}
	return crc
}
