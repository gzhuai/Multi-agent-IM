package handler

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
)

type Proxy struct {
	imCoreURL  string
	client     *http.Client
	wsProxy    *httputil.ReverseProxy
}

func NewProxy(imCoreURL string) *Proxy {
	target, _ := url.Parse(fmt.Sprintf("http://%s", imCoreURL))
	return &Proxy{
		imCoreURL: imCoreURL,
		client:    &http.Client{},
		wsProxy:   httputil.NewSingleHostReverseProxy(target),
	}
}

func (p *Proxy) Health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "ok",
		"service": "api-gateway",
	})
}

func (p *Proxy) ProxyToIMCore(w http.ResponseWriter, r *http.Request) {
	target, err := url.Parse(fmt.Sprintf("http://%s%s", p.imCoreURL, r.URL.Path))
	if err != nil {
		http.Error(w, "bad gateway config", http.StatusInternalServerError)
		return
	}
	if r.URL.RawQuery != "" {
		target.RawQuery = r.URL.RawQuery
	}

	proxyReq, err := http.NewRequestWithContext(r.Context(), r.Method, target.String(), r.Body)
	if err != nil {
		http.Error(w, "proxy request error", http.StatusInternalServerError)
		return
	}
	proxyReq.Header = r.Header.Clone()

	resp, err := p.client.Do(proxyReq)
	if err != nil {
		log.Printf("Proxy error: %v", err)
		http.Error(w, "upstream unavailable", http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	for k, v := range resp.Header {
		for _, vv := range v {
			w.Header().Add(k, vv)
		}
	}
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body)
}

// ProxyWebSocket forwards WebSocket upgrade requests to IM Core.
func (p *Proxy) ProxyWebSocket(w http.ResponseWriter, r *http.Request) {
	// Pass user_id from context as header to IM Core
	userID := r.Context().Value("user_id")
	if userID != nil {
		r.Header.Set("X-User-ID", userID.(string))
	}
	p.wsProxy.ServeHTTP(w, r)
}
