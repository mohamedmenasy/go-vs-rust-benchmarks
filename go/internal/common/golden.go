package common

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// RepoRoot walks up from the working directory to the directory holding
// bench.toml. Tests use it to find spec/golden.json and fixtures.
func RepoRoot() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "bench.toml")); err == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", fmt.Errorf("bench.toml not found above working directory")
		}
		dir = parent
	}
}

// LoadGolden decodes spec/golden.json into v.
func LoadGolden(v any) error {
	root, err := RepoRoot()
	if err != nil {
		return err
	}
	b, err := os.ReadFile(filepath.Join(root, "spec", "golden.json"))
	if err != nil {
		return err
	}
	return json.Unmarshal(b, v)
}
