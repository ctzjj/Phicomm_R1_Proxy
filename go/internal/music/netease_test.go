package music

import (
	"encoding/hex"
	"testing"
)

// FIPS-197 AES-128 ECB test vector.
func TestEncryptECB(t *testing.T) {
	key, _ := hex.DecodeString("000102030405060708090a0b0c0d0e0f")
	plain, _ := hex.DecodeString("00112233445566778899aabbccddeeff")
	out, err := encryptECB(plain, key)
	if err != nil {
		t.Fatalf("encrypt: %v", err)
	}
	// PKCS#7 always adds a block, so only the first block is checked here.
	if got := hex.EncodeToString(out[:16]); got != "69c4e0d86a7b0430d8cdb78070b4c55a" {
		t.Fatalf("block = %s", got)
	}
	if len(out) != 32 {
		t.Fatalf("padded length = %d, want 32", len(out))
	}
}

func TestEncryptEParams(t *testing.T) {
	got, err := encryptEParams(map[string]any{"method": "POST"})
	if err != nil {
		t.Fatalf("encryptEParams: %v", err)
	}
	if len(got) == 0 || got != upper(got) {
		t.Fatalf("eparams not upper-case hex: %q", got)
	}
	for _, c := range got {
		if (c < '0' || c > '9') && (c < 'A' || c > 'F') {
			t.Fatalf("invalid hex char %q in %q", c, got)
		}
	}
}

func upper(s string) string {
	b := []byte(s)
	for i := range b {
		if b[i] >= 'a' && b[i] <= 'z' {
			b[i] -= 'a' - 'A'
		}
	}
	return string(b)
}
