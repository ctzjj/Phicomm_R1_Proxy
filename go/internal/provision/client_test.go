package provision

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestScanAndConfigure(t *testing.T) {
	var gotBody map[string]string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/getwifilist":
			_, _ = io.WriteString(w, "[]")
		case "/api/wifilist":
			w.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(w, `[{"level":-52,"mac":"aa:bb:cc:dd:ee:ff","secure":"WPA","ssid":"Tomato"},{"level":-70,"mac":"11:22:33:44:55:66","secure":"WEP","ssid":"Old"}]`)
		case "/api/configwifi":
			body, _ := io.ReadAll(r.Body)
			_ = json.Unmarshal(body, &gotBody)
			w.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(w, `{"device_id":"00FC7C023AF9BD6FCDDDB575","model":"R1","rom":"1.0.0.3448"}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	c := &Client{Base: srv.URL, HTTP: srv.Client()}
	nets, err := c.Scan(context.Background(), 3*time.Second)
	if err != nil {
		t.Fatalf("scan: %v", err)
	}
	if len(nets) != 2 || nets[0].SSID != "Tomato" || nets[0].Level != -52 || nets[0].Secure != "WPA" {
		t.Fatalf("unexpected networks: %+v", nets)
	}

	info, err := c.Configure(context.Background(), "Tomato", "wlan@518", "WPA", "")
	if err != nil {
		t.Fatalf("configure: %v", err)
	}
	if info.DeviceID != "00FC7C023AF9BD6FCDDDB575" || info.Model != "R1" || info.ROM != "1.0.0.3448" {
		t.Fatalf("unexpected device info: %+v", info)
	}
	want := map[string]string{"ssid": "Tomato", "password": "wlan@518", "secure": "WPA", "mac": ""}
	for k, v := range want {
		if gotBody[k] != v {
			t.Fatalf("configwifi %s = %q, want %q", k, gotBody[k], v)
		}
	}
}

func TestParseNetworkListVariants(t *testing.T) {
	bare := []byte(`[{"ssid":"a","level":1}]`)
	obj := []byte(`{"wifilist":[{"ssid":"b","level":2}]}`)
	for _, in := range [][]byte{bare, obj} {
		nets, err := parseNetworkList(in)
		if err != nil {
			t.Fatalf("parse %s: %v", in, err)
		}
		if len(nets) != 1 {
			t.Fatalf("parse %s: got %d networks", in, len(nets))
		}
	}
}

func TestNewNormalizesBase(t *testing.T) {
	c := New("192.168.43.1", 8989)
	if c.Base != "http://192.168.43.1:8989" {
		t.Fatalf("base = %q", c.Base)
	}
	c = New("http://10.0.0.1:9000", 8989)
	if c.Base != "http://10.0.0.1:9000" {
		t.Fatalf("base = %q", c.Base)
	}
}
