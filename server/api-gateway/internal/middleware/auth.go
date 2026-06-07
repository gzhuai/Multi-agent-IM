package middleware

import (
	"context"
	"net/http"
	"strings"

	"github.com/multi-agent-im/api-gateway/internal/service"
)

type contextKey string

const (
	UserIDKey   contextKey = "user_id"
	UsernameKey contextKey = "username"
)

// AuthRequired validates JWT and injects user info into context.
func AuthRequired(authSvc *service.AuthService) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			token := extractToken(r)
			if token == "" {
				http.Error(w, `{"error":"missing authorization header"}`, http.StatusUnauthorized)
				return
			}

			userID, username, err := authSvc.ValidateToken(token)
			if err != nil {
				http.Error(w, `{"error":"invalid or expired token"}`, http.StatusUnauthorized)
				return
			}

			ctx := context.WithValue(r.Context(), UserIDKey, userID)
			ctx = context.WithValue(ctx, UsernameKey, username)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// AuthOptional extracts JWT if present but doesn't block unauthenticated requests.
func AuthOptional(authSvc *service.AuthService) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			token := extractToken(r)
			if token != "" {
				userID, username, err := authSvc.ValidateToken(token)
				if err == nil {
					ctx := context.WithValue(r.Context(), UserIDKey, userID)
					ctx = context.WithValue(ctx, UsernameKey, username)
					r = r.WithContext(ctx)
				}
			}
			next.ServeHTTP(w, r)
		})
	}
}

func extractToken(r *http.Request) string {
	auth := r.Header.Get("Authorization")
	if strings.HasPrefix(auth, "Bearer ") {
		return strings.TrimPrefix(auth, "Bearer ")
	}
	// Also support token in query param (for WebSocket)
	if tok := r.URL.Query().Get("token"); tok != "" {
		return tok
	}
	return ""
}

func UserIDFromContext(ctx context.Context) string {
	if id, ok := ctx.Value(UserIDKey).(string); ok {
		return id
	}
	return ""
}

func UsernameFromContext(ctx context.Context) string {
	if name, ok := ctx.Value(UsernameKey).(string); ok {
		return name
	}
	return ""
}
