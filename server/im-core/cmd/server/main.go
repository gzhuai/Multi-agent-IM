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

	// WebSocket Hub (with message persistence)
	hub := handler.NewHub(func(msg *domain.Message) error {
		return msgService.PersistMessage(context.Background(), msg)
	})

	// Channel message handler: for group channels, dispatch to ALL agent members.
	// Each agent gets its own background goroutine to call the Agent Runtime.
	hub.SetChannelMessageHandler(func(msg *domain.Message) {
		// Get agent members of this channel
		agentIDs, err := msgService.GetChannelAgents(context.Background(), msg.ChannelID)
		if err != nil {
			log.Printf("Channel agents query error: %v", err)
			return
		}
		if len(agentIDs) == 0 {
			return // No agents in this channel, nothing to do
		}

		log.Printf("Dispatching to %d agent(s) in channel %s", len(agentIDs), msg.ChannelID)

		// Fetch history for context
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

		// Fetch channel member info for participants context
		members, _ := msgService.GetChannelMembers(context.Background(), msg.ChannelID)
		participants := make([]map[string]interface{}, len(members))
		for i, m := range members {
			participants[i] = map[string]interface{}{
				"id": m.MemberID, "type": m.MemberType,
			}
		}

		// Dispatch to each agent in parallel goroutines
		for _, agentID := range agentIDs {
			if agentID == msg.SenderID {
				continue // Don't let an agent reply to its own message
			}
			go func(aid string) {
				resp, err := agentClient.Think(context.Background(), service.ThinkRequest{
					AgentID:      aid,
					ChannelID:    msg.ChannelID,
					Messages:     messages,
					Participants: participants,
				})
				if err != nil {
					log.Printf("Agent %s think error: %v", aid, err)
					return
				}
				if resp != nil && resp.Text != "" {
					hub.BroadcastMessage(&domain.Message{
						ID:         uuid.New().String(),
						ChannelID:  msg.ChannelID,
						SenderID:   aid,
						SenderType: "agent",
						SenderName: aid,
						Content:    resp.Text,
						CreatedAt:  time.Now(),
					})
				}
			}(agentID)
		}
	})

	go hub.Run()

	// Start autonomous messaging: periodically wakes idle agents in group channels
	autonomyMgr := service.NewAutonomyManager(agentClient, msgService)
	autonomyMgr.Start(3 * time.Minute) // wake every 3 minutes

	wsHandler := handler.NewWSHandler(hub, msgService)
	msgHandler := handler.NewMessageHandler(wsHandler)
	channelHandler := handler.NewChannelHandler(msgService, agentClient)

	// Routes
	mux := http.NewServeMux()
	mux.HandleFunc("/health", msgHandler.Health)
	mux.HandleFunc("/ws", wsHandler.HandleWebSocket)
	mux.HandleFunc("/api/messages", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			msgHandler.GetHistory(w, r)
		default:
			w.WriteHeader(http.StatusMethodNotAllowed)
		}
	})
	// Channel routes — register explicit paths for Go 1.22+ mux compatibility
	mux.HandleFunc("/api/channels", channelHandler.ServeHTTP)
	mux.HandleFunc("/api/channels/", channelHandler.ServeHTTP)

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
