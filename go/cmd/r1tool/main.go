// Command r1tool is the Go port of the Phicomm R1 PHP tools:
// binding helper, ASR interception proxy, echo server and the provisioning
// (Wi-Fi configuration) client.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/asr"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/bind"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/home"
	"github.com/ctzjj/Phicomm_R1_Proxy/go/internal/provision"
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

func runASR(args []string) error {
	fs := flag.NewFlagSet("asr", flag.ExitOnError)
	addr := fs.String("addr", ":80", "listen address (must be reachable as asrv3.hivoice.cn)")
	upstream := fs.String("upstream", "47.102.50.144:80", "real ASR server host:port")
	verbose := fs.Bool("v", false, "log every intercepted answer")
	_ = fs.Parse(args)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	s := &asr.Server{Addr: *addr, Upstream: *upstream, Verbose: *verbose}
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
