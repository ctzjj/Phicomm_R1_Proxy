// Command r1tool is the Go port of the Phicomm R1 PHP tools:
// binding helper, ASR interception proxy, echo server and the provisioning
// (Wi-Fi configuration) client.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/asr"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/bind"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/home"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/logbuf"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/provision"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/webui"
)

const usage = `r1tool - Phicomm R1 tools (Go port of the PHP PoCs)

usage: r1tool <command> [flags]

commands:
  bind        binding helper: answer /getUserInfo with {"status":"0"}
  asr         ASR interception proxy: forward to the real ASR service and
              replace music answers with search results
  home        simple TCP echo server
  wifi        list the Wi-Fi networks seen by the speaker (provisioning mode)
  provision   make the speaker join a Wi-Fi network (one-key pairing)
  audiodump   convert a "asr -dump" directory into per-utterance Ogg/Opus files

run "r1tool <command> -h" for the flags of a command.
`

func main() {
	log.SetFlags(log.LstdFlags)
	if len(os.Args) < 2 {
		fmt.Print(usage)
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "bind":
		err = runBind(os.Args[2:])
	case "asr":
		err = runASR(os.Args[2:])
	case "home":
		err = runHome(os.Args[2:])
	case "wifi":
		err = runWifi(os.Args[2:])
	case "provision":
		err = runProvision(os.Args[2:])
	case "audiodump":
		err = runAudioDump(os.Args[2:])
	case "-h", "--help", "help":
		fmt.Print(usage)
		return
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n%s", os.Args[1], usage)
		os.Exit(2)
	}
	if err != nil {
		log.Fatalf("r1tool: %v", err)
	}
}

func runBind(args []string) error {
	fs := flag.NewFlagSet("bind", flag.ExitOnError)
	addr := fs.String("addr", "0.0.0.0:19999", "listen address")
	_ = fs.Parse(args)
	s := &bind.Server{Addr: *addr}
	return s.ListenAndServe()
}

// mediaBaseOf returns the base URL the speaker should use for /media.
// The default uses the hijacked aios-home.hivoice.cn host name (the same
// domain the provisioning/binding hijack already points at this machine), so
// the tool keeps working for anyone who follows the docs instead of baking in
// one LAN address. -media-base overrides it (e.g. a different host or port).
func mediaBaseOf(listen, override string) string {
	if override != "" {
		return strings.TrimRight(override, "/")
	}
	_, port, err := net.SplitHostPort(listen)
	if err != nil {
		port = "8080"
	}
	return "http://aios-home.hivoice.cn:" + port
}

func runASR(args []string) error {
	fs := flag.NewFlagSet("asr", flag.ExitOnError)
	addr := fs.String("addr", ":80", "listen address (must be reachable as asrv3.hivoice.cn)")
	upstream := fs.String("upstream", "", "real ASR server host:port (default: resolve asrv3.hivoice.cn via -dns)")
	dnsServer := fs.String("dns", "223.5.5.5:53", "DNS server used to resolve asrv3.hivoice.cn")
	verbose := fs.Bool("v", false, "log every intercepted answer")
	dumpDir := fs.String("dump", "", "directory to dump raw request/response (headers, body, hexdump)")
	audioDir := fs.String("audio-dir", "", "write each utterance as Ogg/Opus into this directory")
	forward := fs.String("forward", "", "POST each utterance Ogg to this URL (audio/ogg)")
	music := fs.Bool("music", true, "replace music intents with our multi-source search")
	mediaBase := fs.String("media-base", "", "rewrite music urls through <base>/media (default: http://aios-home.hivoice.cn:<port>)")
	nluMode := fs.String("nlu-mode", "default", "default (Yunzhisheng cloud) or custom")
	nluURL := fs.String("nlu-url", "", "custom NLU endpoint (POST audio/ogg)")
	nluKey := fs.String("nlu-key", "", "custom NLU api key")
	nluKeyHeader := fs.String("nlu-key-header", "Authorization", "header carrying the custom NLU key")
	webPort := fs.Int("web-port", 0, "serve the web console on this port (0 = disabled)")
	cfgPath := fs.String("config", "r1tool.json", "settings file (created on first save)")
	_ = fs.Parse(args)

	settings := asr.NewStore(asr.Settings{
		Upstream:     *upstream,
		DNS:          *dnsServer,
		MediaBase:    mediaBaseOf(*addr, *mediaBase),
		Music:        *music,
		Forward:      *forward,
		NLUMode:      asr.NormalizeNLUMode(*nluMode),
		NLUURL:       *nluURL,
		NLUKey:       *nluKey,
		NLUKeyHeader: *nluKeyHeader,
		AudioDir:     *audioDir,
		DumpDir:      *dumpDir,
	})
	// A saved r1tool.json wins over the flag defaults.
	if data, err := os.ReadFile(*cfgPath); err == nil {
		var saved asr.Settings
		if err := json.Unmarshal(data, &saved); err == nil {
			settings.Update(saved)
		}
	} else {
		_ = settings // file missing on first run
	}
	save := func() error {
		data, err := json.MarshalIndent(settings.Get(), "", "  ")
		if err != nil {
			return err
		}
		return os.WriteFile(*cfgPath, data, 0o644)
	}

	logs := logbuf.New()
	log.SetOutput(io.MultiWriter(os.Stderr, logs))

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	s := &asr.Server{Addr: *addr, Verbose: *verbose, Settings: settings}

	if *webPort > 0 {
		ui := &webui.Server{
			Addr:     fmt.Sprintf(":%d", *webPort),
			Settings: settings,
			Logs:     logs,
			Status:   s.Status,
			Save:     save,
		}
		go func() {
			if err := ui.ListenAndServe(); err != nil {
				log.Printf("[web] %v", err)
			}
		}()
	}
	return s.ListenAndServe(ctx)
}

func runHome(args []string) error {
	fs := flag.NewFlagSet("home", flag.ExitOnError)
	addr := fs.String("addr", "0.0.0.0:8883", "listen address")
	_ = fs.Parse(args)
	s := &home.Server{Addr: *addr}
	return s.ListenAndServe()
}

func runWifi(args []string) error {
	fs := flag.NewFlagSet("wifi", flag.ExitOnError)
	gw := fs.String("gw", "192.168.43.1", "speaker gateway in provisioning mode")
	port := fs.Int("port", 8989, "provisioning http port")
	wait := fs.Duration("wait", 20*time.Second, "how long to wait for the scan result")
	asJSON := fs.Bool("json", false, "print raw JSON")
	_ = fs.Parse(args)

	c := provision.New(*gw, *port)
	ctx, cancel := context.WithTimeout(context.Background(), *wait+15*time.Second)
	defer cancel()
	log.Printf("[wifi] scanning via %s", c.Base)
	nets, err := c.Scan(ctx, *wait)
	if err != nil {
		return err
	}
	if *asJSON {
		out, _ := json.MarshalIndent(nets, "", "  ")
		fmt.Println(string(out))
		return nil
	}
	if len(nets) == 0 {
		fmt.Println("no network found (is the speaker in provisioning mode?)")
		return nil
	}
	for i, n := range nets {
		fmt.Printf("[%2d] %-24s %4d  %-5s  %s\n", i, n.SSID, n.Level, n.Secure, n.MAC)
	}
	return nil
}

func runProvision(args []string) error {
	fs := flag.NewFlagSet("provision", flag.ExitOnError)
	gw := fs.String("gw", "192.168.43.1", "speaker gateway in provisioning mode")
	port := fs.Int("port", 8989, "provisioning http port")
	ssid := fs.String("ssid", "", "Wi-Fi SSID to join (required)")
	pass := fs.String("pass", "", "Wi-Fi password")
	secure := fs.String("secure", "WPA", `security type: "WPA", "WEP" or "" for open`)
	mac := fs.String("mac", "", "optional BSSID")
	scan := fs.Bool("scan", false, "list visible networks before configuring")
	_ = fs.Parse(args)

	if *ssid == "" {
		fs.Usage()
		return fmt.Errorf("missing -ssid")
	}
	c := provision.New(*gw, *port)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	log.Printf("[provision] using %s", c.Base)

	if *scan {
		if nets, err := c.Scan(ctx, 20*time.Second); err == nil {
			for i, n := range nets {
				fmt.Printf("[%2d] %-24s %4d  %-5s  %s\n", i, n.SSID, n.Level, n.Secure, n.MAC)
			}
		} else {
			log.Printf("[provision] scan: %v", err)
		}
	}

	log.Printf("[provision] configuring %q (%s)", *ssid, *secure)
	info, err := c.Configure(ctx, *ssid, *pass, *secure, *mac)
	if err != nil {
		return err
	}
	if info.DeviceID == "" && info.Model == "" {
		out, _ := json.Marshal(info.Raw)
		fmt.Printf("[+] configured %q: %s\n", *ssid, string(out))
	} else {
		fmt.Printf("[+] configured %q -> device_id=%s model=%s rom=%s\n", *ssid, info.DeviceID, info.Model, info.ROM)
	}
	fmt.Println("[*] the speaker should now join the network; reconnect your PC to it.")
	return nil
}
