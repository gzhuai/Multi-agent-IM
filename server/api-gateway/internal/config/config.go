package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	Server      ServerConfig
	Database    DatabaseConfig
	IMCoreAddr  string
	AuthSecret  string
}

type ServerConfig struct {
	Host            string
	Port            int
	ReadTimeout     time.Duration
	WriteTimeout    time.Duration
	ShutdownTimeout time.Duration
}

type DatabaseConfig struct {
	Host     string
	Port     int
	User     string
	Password string
	DBName   string
}

func Load() *Config {
	return &Config{
		Server: ServerConfig{
			Host:            envOrDefault("GATEWAY_HOST", "0.0.0.0"),
			Port:            envIntOrDefault("GATEWAY_PORT", 3000),
			ReadTimeout:     10 * time.Second,
			WriteTimeout:    10 * time.Second,
			ShutdownTimeout: 10 * time.Second,
		},
		Database: DatabaseConfig{
			Host:     envOrDefault("DB_HOST", "localhost"),
			Port:     envIntOrDefault("DB_PORT", 5432),
			User:     envOrDefault("DB_USER", "maim"),
			Password: envOrDefault("DB_PASSWORD", "maim_dev"),
			DBName:   envOrDefault("DB_NAME", "multiagent"),
		},
		IMCoreAddr: envOrDefault("IM_CORE_ADDR", "localhost:8080"),
		AuthSecret: envOrDefault("AUTH_SECRET", "dev-secret-change-in-production"),
	}
}

func envOrDefault(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

func envIntOrDefault(key string, defaultVal int) int {
	if val := os.Getenv(key); val != "" {
		if intVal, err := strconv.Atoi(val); err == nil {
			return intVal
		}
	}
	return defaultVal
}
