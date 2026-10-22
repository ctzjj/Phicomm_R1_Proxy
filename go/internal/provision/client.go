// Package provision talks to the Phicomm R1 provisioning service.
//
// When the speaker enters provisioning mode it starts a soft AP
// "Phicomm_R1_xxxx" (gateway 192.168.43.1) and an HTTP service on port 8989:
//
//	GET  /api/getwifilist          trigger a scan (may return [] while scanning)
//	GET  /api/wifilist             current scan result
//	POST /api/configwifi           {"ssid","password","secure","mac"}
//
// After a successful POST the speaker leaves AP mode and joins the given
// network.
package provision

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// Network is one Wi-Fi network reported by the speaker.
type Network struct {
	Level  int    `json:"level"`
	MAC    string `json:"mac"`
	Secure string `json:"secure"`
	SSID   string `json:"ssid"`
}

// DeviceInfo is the reply of /api/configwifi.
type DeviceInfo struct {
	DeviceID string         `json:"device_id"`
	Model    string         `json:"model"`
	ROM      string         `json:"rom"`
	Raw      map[string]any `json:"-"`
}

// Client is a provisioning API client.
type Client struct {
	Base string // e.g. http://192.168.43.1:8989
	HTTP *http.Client
}

// New returns a client for the given gateway and port.
func New(gateway string, port int) *Client {
	if port <= 0 {
		port = 8989
	}
	base := gateway
	if !strings.Contains(base, "://") {
		base = "http://" + base
	}
	u, err := url.Parse(base)
	if err == nil {
		if u.Port() == "" {
			u.Host = net.JoinHostPort(u.Hostname(), strconv.Itoa(port))
		}
		base = strings.TrimRight(u.String(), "/")
	}
	return &Client{Base: base, HTTP: &http.Client{Timeout: 15 * time.Second}}
}

// ScanOnce fetches the current scan list without triggering a new scan.
func (c *Client) ScanOnce(ctx context.Context) ([]Network, error) {
	return c.getList(ctx, "/api/wifilist")
}

// Scan triggers a Wi-Fi scan on the speaker and polls until a list is
// available (the device returns [] while its scan is still running).
func (c *Client) Scan(ctx context.Context, wait time.Duration) ([]Network, error) {
	// Trigger the scan; ignore errors, /api/wifilist may already have data.
	_, _ = c.getList(ctx, "/api/getwifilist")

	if wait <= 0 {
		wait = 20 * time.Second
	}
	deadline := time.Now().Add(wait)
	for {
		nets, err := c.ScanOnce(ctx)
		if err == nil && len(nets) > 0 {
			return nets, nil
		}
		if time.Now().After(deadline) {
			if err != nil {
				return nil, err
			}
			return nets, nil
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(time.Second):
		}
	}
}

// Configure tells the speaker to join ssid/password.
func (c *Client) Configure(ctx context.Context, ssid, password, secure, mac string) (*DeviceInfo, error) {
	if ssid == "" {
		return nil, errors.New("provision: empty ssid")
	}
	if secure == "" {
		secure = "WPA"
	}
	reqBody, _ := json.Marshal(map[string]string{
		"ssid":     ssid,
		"password": password,
		"secure":   secure,
		"mac":      mac,
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.Base+"/api/configwifi", bytes.NewReader(reqBody))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode/100 != 2 {
		return nil, fmt.Errorf("provision: http %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	info := &DeviceInfo{}
	if err := json.Unmarshal(body, info); err != nil {
		// Not JSON: still report success with the raw text.
		return &DeviceInfo{Raw: map[string]any{"raw": strings.TrimSpace(string(body))}}, nil
	}
	_ = json.Unmarshal(body, &info.Raw)
	return info, nil
}

func (c *Client) getList(ctx context.Context, path string) ([]Network, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.Base+path, nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode/100 != 2 {
		return nil, fmt.Errorf("provision: http %d", resp.StatusCode)
	}
	return parseNetworkList(body)
}

// parseNetworkList accepts a bare JSON array or an object containing the
// array under a common key (the firmware versions differ).
func parseNetworkList(body []byte) ([]Network, error) {
	trimmed := bytes.TrimSpace(body)
	if len(trimmed) == 0 {
		return nil, nil
	}
	if trimmed[0] == '[' {
		var nets []Network
		if err := json.Unmarshal(trimmed, &nets); err != nil {
			return nil, err
		}
		return nets, nil
	}
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(trimmed, &obj); err != nil {
		return nil, err
	}
	for _, key := range []string{"wifilist", "wifiList", "list", "data", "result"} {
		if raw, ok := obj[key]; ok {
			var nets []Network
			if err := json.Unmarshal(raw, &nets); err == nil {
				return nets, nil
			}
		}
	}
	return nil, nil
}
