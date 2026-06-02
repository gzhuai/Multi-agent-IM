package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/multi-agent-im/api-gateway/internal/config"
	"github.com/multi-agent-im/api-gateway/internal/handler"
	"github.com/multi-agent-im/api-gateway/internal/middleware"
	"github.com/multi-agent-im/api-gateway/internal/service"
)

func main() {
	cfg := config.Load()

	log.Printf("Starting API Gateway on %s:%d", cfg.Server.Host, cfg.Server.Port)

	// Connect to PostgreSQL
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsnFromConfig(cfg))
	if err != nil {
		log.Printf("WARN: PostgreSQL not available: %v (auth disabled)", err)
	} else {
		defer pool.Close()
		log.Println("PostgreSQL connected for auth")
	}

	// Auth service
	authSvc := service.NewAuthService(pool, cfg.AuthSecret)

	// Handlers
	authHandler := handler.NewAuthHandler(authSvc)
	proxy := handler.NewProxy(cfg.IMCoreAddr)

	mux := http.NewServeMux()

	// Public auth routes
	mux.HandleFunc("/api/auth/register", authHandler.Register)
	mux.HandleFunc("/api/auth/login", authHandler.Login)

	// Protected routes
	protectedMux := http.NewServeMux()
	protectedMux.HandleFunc("/api/auth/me", authHandler.Me)
	protectedMux.HandleFunc("/api/", proxy.ProxyToIMCore)
	protectedMux.HandleFunc("/ws", proxy.ProxyWebSocket)

	// Health (public)
	mux.HandleFunc("/health", proxy.Health)

	// Root: if path isn't matched by mux, try protected routes (with auth)
	wrappedMux := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Check if the request path matches a public route
		if r.URL.Path == "/health" ||
			r.URL.Path == "/api/auth/register" ||
			r.URL.Path == "/api/auth/login" {
			mux.ServeHTTP(w, r)
			return
		}
		// Protected: apply auth middleware
		middleware.AuthRequired(authSvc)(protectedMux).ServeHTTP(w, r)
	})

	// Global middleware
	var h http.Handler = wrappedMux
	h = middleware.Logging(h)

	server := &http.Server{
		Addr:         fmt.Sprintf("%s:%d", cfg.Server.Host, cfg.Server.Port),
		Handler:      h,
		ReadTimeout:  cfg.Server.ReadTimeout,
		WriteTimeout: cfg.Server.WriteTimeout,
	}

	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		<-sigCh
		log.Println("Shutting down...")
		server.Shutdown(context.Background())
	}()

	if err := server.ListenAndServe(); err != http.ErrServerClosed {
		log.Fatalf("Server error: %v", err)
	}
	log.Println("Server stopped")
}

func dsnFromConfig(cfg *config.Config) string {
	return fmt.Sprintf(
		"postgres://%s:%s@%s:%d/%s?sslmode=disable",
		cfg.Database.User, cfg.Database.Password,
		cfg.Database.Host, cfg.Database.Port,
		cfg.Database.DBName,
	)
}
