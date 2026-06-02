package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/multi-agent-im/im-core/internal/config"
	"github.com/multi-agent-im/im-core/internal/domain"
	"github.com/multi-agent-im/im-core/internal/handler"
	"github.com/multi-agent-im/im-core/internal/repository"
	"github.com/multi-agent-im/im-core/internal/service"
)

func main() {
	cfg := config.Load()

	log.Printf("Starting IM Core on %s:%d", cfg.Server.Host, cfg.Server.Port)

	ctx := context.Background()

	// PostgreSQL
	pgStore, err := repository.NewPostgresStore(ctx, cfg.DSN())
	if err != nil {
		log.Printf("WARN: PostgreSQL not available: %v", err)
	} else {
		defer pgStore.Close()
		log.Println("PostgreSQL connected")
	}

	// Redis
	redisAddr := fmt.Sprintf("%s:%d", cfg.Redis.Host, cfg.Redis.Port)
	redisStore, err := repository.NewRedisStore(ctx, redisAddr, cfg.Redis.Password, cfg.Redis.DB)
	if err != nil {
		log.Printf("WARN: Redis not available: %v", err)
	} else {
		defer redisStore.Close()
		log.Println("Redis connected")
	}

	// Services
	msgService := service.NewMessageService(pgStore, redisStore)
	agentClient := service.NewAgentClient("http://localhost:50051")

	// WebSocket Hub (with message persistence + agent mention handling)
	hub := handler.NewHub(func(msg *domain.Message) error {
		return msgService.PersistMessage(context.Background(), msg)
	})

	// Agent mention handler: forwards messages with @mentions to Agent Runtime
	hub.SetAgentMentionHandler(func(msg *domain.Message) (*domain.Message, error) {
		// Fetch recent messages for context
		history, _ := msgService.GetChannelHistory(context.Background(), msg.ChannelID, 20)
		messages := make([]map[string]interface{}, len(history)+1)
		messages[0] = map[string]interface{}{
			"role": "user", "content": msg.Content,
			"sender_name": msg.SenderName, "sender_type": msg.SenderType,
		}
		for i, h := range history {
			messages[i+1] = map[string]interface{}{
				"role": "user", "content": h.Content,
				"sender_name": h.SenderName, "sender_type": h.SenderType,
			}
		}

		// Call Agent Runtime (uses first mention as agent name for now)
		agentName := msg.Mentions[0]
		resp, err := agentClient.Think(context.Background(), service.ThinkRequest{
			AgentID:      agentName, // Mention IS the agent name/ID for Phase 1
			ChannelID:    msg.ChannelID,
			Messages:     messages,
			Participants: []map[string]interface{}{},
		})
		if err != nil {
			log.Printf("Agent think error: %v", err)
			return nil, err
		}

		return &domain.Message{
			ID:         uuid.New().String(),
			ChannelID:  msg.ChannelID,
			SenderID:   agentName,
			SenderType: "agent",
			SenderName: agentName,
			Content:    resp.Text,
			CreatedAt:  time.Now(),
		}, nil
	})

	go hub.Run()

	wsHandler := handler.NewWSHandler(hub, msgService)
	msgHandler := handler.NewMessageHandler(wsHandler)

	// Routes
	mux := http.NewServeMux()
	mux.HandleFunc("/health", msgHandler.Health)
	mux.HandleFunc("/ws", wsHandler.HandleWebSocket)
	mux.HandleFunc("/api/messages", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			msgHandler.GetHistory(w, r)
		case http.MethodPost:
			// REST message send (fallback, primary is WebSocket)
			w.WriteHeader(http.StatusNotImplemented)
		default:
			w.WriteHeader(http.StatusMethodNotAllowed)
		}
	})

	server := &http.Server{
		Addr:    fmt.Sprintf("%s:%d", cfg.Server.Host, cfg.Server.Port),
		Handler: mux,
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
