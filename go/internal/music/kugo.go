package music

import "context"

// Kugo is kept for parity with the PHP PoC (Provider\Music\Kugo). The PHP
// version only fetched the search page and dumped it, so there was never a
// working implementation; the format is left untouched.
type Kugo struct{}

// NewKugo returns a Kugo provider.
func NewKugo() *Kugo { return &Kugo{} }

// Search is not implemented (mirrors the PHP PoC, which just dumped the
// response of the Kuwo search API).
func (k *Kugo) Search(ctx context.Context, keyword string, f *Format) error {
	return nil
}
