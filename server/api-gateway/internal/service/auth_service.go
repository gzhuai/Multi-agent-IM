package service

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"

	"github.com/multi-agent-im/api-gateway/internal/model"
)

var (
	ErrUserExists       = errors.New("username already taken")
	ErrInvalidCreds     = errors.New("invalid username or password")
	ErrUserNotFound     = errors.New("user not found")
)

type AuthService struct {
	db         *pgxpool.Pool
	jwtSecret  []byte
}

func NewAuthService(db *pgxpool.Pool, jwtSecret string) *AuthService {
	return &AuthService{db: db, jwtSecret: []byte(jwtSecret)}
}

func (s *AuthService) Register(ctx context.Context, req model.RegisterRequest) (*model.AuthResponse, error) {
	if req.Username == "" || req.Password == "" {
		return nil, fmt.Errorf("username and password are required")
	}
	if len(req.Password) < 6 {
		return nil, fmt.Errorf("password must be at least 6 characters")
	}

	// Check if username exists
	var exists bool
	err := s.db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM users WHERE username=$1)`, req.Username).Scan(&exists)
	if err != nil {
		return nil, fmt.Errorf("check username: %w", err)
	}
	if exists {
		return nil, ErrUserExists
	}

	// Hash password
	hash, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		return nil, fmt.Errorf("hash password: %w", err)
	}

	userID := genID()
	displayName := req.DisplayName
	if displayName == "" {
		displayName = req.Username
	}

	_, err = s.db.Exec(ctx,
		`INSERT INTO users (id, organization_id, username, display_name, password_hash)
		 VALUES ($1, (SELECT id FROM organizations LIMIT 1), $2, $3, $4)`,
		userID, req.Username, displayName, string(hash),
	)
	if err != nil {
		return nil, fmt.Errorf("insert user: %w", err)
	}

	token, err := s.issueToken(userID, req.Username)
	if err != nil {
		return nil, err
	}

	return &model.AuthResponse{Token: token, UserID: userID, DisplayName: displayName}, nil
}

func (s *AuthService) Login(ctx context.Context, req model.LoginRequest) (*model.AuthResponse, error) {
	var user model.User
	err := s.db.QueryRow(ctx,
		`SELECT id, username, display_name, password_hash FROM users WHERE username=$1`,
		req.Username,
	).Scan(&user.ID, &user.Username, &user.DisplayName, &user.PasswordHash)
	if err != nil {
		return nil, ErrInvalidCreds
	}

	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(req.Password)); err != nil {
		return nil, ErrInvalidCreds
	}

	token, err := s.issueToken(user.ID, user.Username)
	if err != nil {
		return nil, err
	}

	return &model.AuthResponse{Token: token, UserID: user.ID, DisplayName: user.DisplayName}, nil
}

func (s *AuthService) issueToken(userID, username string, role ...string) (string, error) {
	userRole := "member"
	if len(role) > 0 && role[0] != "" {
		userRole = role[0]
	}
	claims := jwt.MapClaims{
		"sub":      userID,
		"username": username,
		"role":     userRole,
		"iat":      time.Now().Unix(),
		"exp":      time.Now().Add(72 * time.Hour).Unix(),
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(s.jwtSecret)
}

func (s *AuthService) ValidateToken(tokenString string) (string, string, string, error) {
	token, err := jwt.Parse(tokenString, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return s.jwtSecret, nil
	})
	if err != nil {
		return "", "", "", err
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok || !token.Valid {
		return "", "", "", fmt.Errorf("invalid token")
	}
	userID, _ := claims["sub"].(string)
	username, _ := claims["username"].(string)
	role, _ := claims["role"].(string)
	if role == "" {
		role = "member"
	}
	return userID, username, role, nil
}

func genID() string {
	b := make([]byte, 16)
	rand.Read(b)
	return hex.EncodeToString(b)
}
