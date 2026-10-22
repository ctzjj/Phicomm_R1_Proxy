package asr

import (
	"context"
	"fmt"
	"net"
	"sync"
	"time"
)

// upstreamHost is the real ASR host name; it is resolved through an external
// resolver (see upstreamResolver) because the local one is hijacked to us.
const upstreamHost = "asrv3.hivoice.cn"

// upstreamResolver resolves upstreamHost through a specific DNS server and
// caches the IPv4 for a few minutes.
type upstreamResolver struct {
	mu  sync.Mutex
	ip  string
	at  time.Time
	dns string
}

func newUpstreamResolver(dns string) *upstreamResolver {
	if dns == "" {
		dns = "223.5.5.5:53"
	}
	if _, _, err := net.SplitHostPort(dns); err != nil {
		dns = net.JoinHostPort(dns, "53")
	}
	return &upstreamResolver{dns: dns}
}

// Resolve returns the cached ip:80, refreshing it every 5 minutes.
func (r *upstreamResolver) Resolve(ctx context.Context, dns string) (string, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if dns != "" {
		if _, _, err := net.SplitHostPort(dns); err != nil {
			dns = net.JoinHostPort(dns, "53")
		}
		if dns != r.dns {
			r.dns = dns
			r.ip = ""
		}
	}
	if r.ip != "" && time.Since(r.at) < 5*time.Minute {
		return r.ip + ":80", nil
	}
	res := &net.Resolver{
		PreferGo: true,
		Dial: func(ctx context.Context, network, _ string) (net.Conn, error) {
			d := net.Dialer{Timeout: 4 * time.Second}
			return d.DialContext(ctx, "udp", r.dns)
		},
	}
	addrs, err := res.LookupIPAddr(ctx, upstreamHost)
	if err != nil {
		return "", fmt.Errorf("resolve %s via %s: %w", upstreamHost, r.dns, err)
	}
	for _, a := range addrs {
		if ip4 := a.IP.To4(); ip4 != nil {
			r.ip = ip4.String()
			r.at = time.Now()
			return r.ip + ":80", nil
		}
	}
	return "", fmt.Errorf("resolve %s: no IPv4 address", upstreamHost)
}

// Invalidate drops the cache so the next call re-resolves.
func (r *upstreamResolver) Invalidate() {
	r.mu.Lock()
	r.ip = ""
	r.mu.Unlock()
}

// ResolveUpstream resolves the real asrv3 ip once (used at startup for logs).
func ResolveUpstream(ctx context.Context, dns string) (string, error) {
	return newUpstreamResolver(dns).Resolve(ctx, dns)
}
